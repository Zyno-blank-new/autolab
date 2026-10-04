"""The model proposes; deterministic policy decides permission and readiness."""
import math
from datetime import datetime
from pydantic import ValidationError
from autolab import schemas as s
from autolab.ledger.repository import TABLES
from .budget import calculate_budget, calculate_time
from .models import ControlStage as C, ProjectSnapshot, ValidationResult, ValidationStatus as V
from .role_registry import RoleRegistry
from .state_machine import (approval_for, charter_fingerprint, current_analysis, current_implementation,
                            current_readiness, current_run, derive_control_state, implementation_passes,
                            latest_review, readiness_passes, selected_experiment, selected_hypothesis,
                            hypothesis_for_decision, latest_versions, candidate_for_selection)

A = s.PlannerAction
CONSEQUENTIAL = {A.PREPARE_RESOURCES, A.IMPLEMENT_EXPERIMENT, A.RUN_EXPERIMENT}


class DecisionValidator:
    def __init__(self, roles: RoleRegistry | None = None):
        self.roles = roles or RoleRegistry()

    def validate(self, proposal, snapshot: ProjectSnapshot, *, expected_decision_id: str | None = None,
                 expected_charter_fingerprint: str | None = None, now: datetime | None = None) -> ValidationResult:
        try:
            # Revalidate instances as well: Pydantic model_copy bypasses checks.
            decision = s.NextDecision.model_validate(proposal.model_dump() if isinstance(proposal, s.NextDecision) else proposal)
        except ValidationError:
            return ValidationResult(status=V.INVALID, reasons=["Output does not match canonical NextDecision; charter edits and unknown fields are forbidden."])
        reasons = []
        if decision.project_id != snapshot.charter.project_id:
            reasons.append("Decision project_id does not match the Research Charter.")
        if expected_decision_id is not None and decision.decision_id != expected_decision_id:
            reasons.append("decision_id must equal the reserved decision ID.")
        if expected_charter_fingerprint is not None and charter_fingerprint(snapshot.authorized_scope or snapshot.charter) != expected_charter_fingerprint:
            reasons.append("Research Charter changed during planning; human approval is required.")
        if decision.action == A.STOP:
            if decision.target_agent not in (None, "planner"):
                reasons.append("STOP targets null or planner.")
        elif decision.target_agent not in self.roles.roles:
            reasons.append("Unknown target role.")
        elif decision.target_agent not in self.roles.action_targets[decision.action]:
            reasons.append("Target role is incompatible with the requested action.")
        identifiers = {snapshot.charter.project_id}
        if snapshot.authorized_scope:
            identifiers.add(snapshot.authorized_scope.project_id)
        for field in type(snapshot).model_fields:
            values = getattr(snapshot, field)
            if isinstance(values, list):
                for record in values:
                    table = TABLES[type(record)]
                    identifiers.add(getattr(record, table.id_field))
        from autolab.feasibility.persistence import current_assessment, current_packet
        assessment, packet = current_assessment(snapshot), current_packet(snapshot)
        if assessment:
            identifiers.add(assessment.assessment_id)
        if packet:
            identifiers.add(packet.packet_id)
        from autolab.preparation.manifest import current_manifest, current_plan
        manifest, plan = current_manifest(snapshot), current_plan(snapshot)
        if manifest: identifiers.add(manifest.manifest_id)
        if plan: identifiers.add(plan.plan_id)
        if any(identifier not in identifiers for identifier in decision.required_context_ids):
            reasons.append("required_context_ids contains a missing or foreign-project record.")
        budget = calculate_budget(snapshot)
        if decision.action != A.STOP and not math.isclose(decision.remaining_budget_usd, budget.remaining_budget_usd, rel_tol=0, abs_tol=0.000001):
            reasons.append("remaining_budget_usd must match known ledger costs.")
        stage = derive_control_state(snapshot)
        consequential = decision.action in CONSEQUENTIAL or (
            decision.action == A.COLLECT_MORE_DATA and decision.target_agent == "preparation")
        if decision.action != A.STOP:
            if stage in (C.PAUSED, C.COMPLETED):
                reasons.append(f"Project is {stage}; only STOP is permitted.")
            if stage == C.BLOCKED and consequential:
                reasons.append("Blocked project cannot start consequential work; revise the plan or resolve the block first.")
            if stage == C.RUNNING:
                reasons.append("A run is active; wait for its result or STOP.")
        if reasons:
            return ValidationResult(status=V.INVALID, reasons=reasons)
        if decision.action == A.STOP:
            return ValidationResult(status=V.VALID)
        from .adaptive import work_block, decision_receipt, state_pin
        receipt = decision_receipt(snapshot, decision.decision_id)
        if receipt and receipt.payload.get('dispatch_pin') != state_pin(snapshot):
            return ValidationResult(status=V.INVALID, reasons=['Adaptive decision scientific snapshot is stale; ask Planner again.'])
        block = work_block(snapshot, decision.action)
        if block:
            return ValidationResult(status=V.INVALID, reasons=[block])
        time = calculate_time(snapshot, now)
        if time.remaining_minutes == 0 and decision.action != A.REQUEST_HUMAN_APPROVAL:
            return ValidationResult(status=V.TIME_BLOCKED, reasons=["Research runtime limit is exhausted."])
        experiment = selected_experiment(snapshot)
        hypothesis = hypothesis_for_decision(snapshot, decision)
        action, target = decision.action, decision.target_agent
        def invalid(message):
            return ValidationResult(status=V.INVALID, reasons=[message])
        if action in (A.REFINE_HYPOTHESIS, A.ACCEPT_HYPOTHESIS, A.REJECT_HYPOTHESIS, A.RUN_FOLLOWUP):
            explicit = [h for h in latest_versions(snapshot.hypotheses, 'hypothesis_id') if h.hypothesis_id in decision.required_context_ids]
            if len(explicit) > 1 or (explicit and (not hypothesis or explicit[0] != hypothesis)):
                return invalid('Hypothesis action must target the current exact selected hypothesis.')
            if hypothesis and hypothesis.version != max(h.version for h in snapshot.hypotheses if h.hypothesis_id == hypothesis.hypothesis_id):
                return invalid('Selected hypothesis version is stale.')
        if action in (A.REFINE_HYPOTHESIS, A.DESIGN_EXPERIMENT) and current_run(snapshot):
            from autolab.analysis.persistence import reviewed_analysis
            refined = action == A.DESIGN_EXPERIMENT and hypothesis and experiment and hypothesis.version > experiment.hypothesis_version and any(
                e.event_type == 'HYPOTHESIS_REFINED' and e.actor == 'hypothesis' and e.target_id == hypothesis.hypothesis_id
                and e.payload.get('version') == hypothesis.version and e.payload.get('reviewed_parent_result') for e in snapshot.events)
            if not reviewed_analysis(snapshot) and not refined:
                return invalid('Post-result refinement/design requires current reviewed analysis.')
        if action == A.GENERATE_HYPOTHESES and not snapshot.evidence:
            from autolab.analysis.persistence import reviewed_analysis
            if not reviewed_analysis(snapshot):
                return invalid("GENERATE_HYPOTHESES requires scientific evidence.")
        if action in (A.REFINE_HYPOTHESIS, A.REJECT_HYPOTHESIS, A.ACCEPT_HYPOTHESIS) and not snapshot.hypotheses:
            return invalid("This action requires an existing hypothesis.")
        if action == A.ACCEPT_HYPOTHESIS:
            analysis = current_analysis(snapshot)
            from autolab.analysis.persistence import reviewed_analysis
            review = latest_review(snapshot, s.ScientificAnalysis, analysis.analysis_id, analysis.version, 'analysis') if analysis else None
            if not reviewed_analysis(snapshot, analysis) or not analysis or analysis.hypothesis_assessment not in (s.HypothesisAssessment.SUPPORTED, s.HypothesisAssessment.PARTIALLY_SUPPORTED) or not review or review.verdict != s.ReviewVerdict.PASS:
                return invalid("Tentative acceptance requires supportive measured analysis and PASS scientific review.")
        if action == A.REJECT_HYPOTHESIS and snapshot.runs:
            from autolab.analysis.persistence import reviewed_analysis
            if not reviewed_analysis(snapshot):
                return invalid("Result-based hypothesis rejection requires current reviewed analysis.")
        if action == A.DESIGN_EXPERIMENT:
            from .adaptive import hypothesis_disposition
            if hypothesis_disposition(snapshot, hypothesis) == 'HYPOTHESIS_REJECTED':
                return invalid('Rejected hypothesis requires a new reviewed refinement/replacement before design.')
            if not hypothesis or hypothesis.status == s.HypothesisStatus.REJECTED:
                return invalid("DESIGN_EXPERIMENT requires a selected, non-rejected hypothesis.")
            if target == "critic":
                if not experiment and not snapshot.candidates:
                    return invalid("Experiment critique requires a candidate or ExperimentSpec.")
            else:
                review = latest_review(snapshot, s.Hypothesis, hypothesis.hypothesis_id, hypothesis.version)
                if not review or review.verdict != s.ReviewVerdict.PASS:
                    return invalid("Experiment design requires a PASS hypothesis review.")
        if action == A.SELECT_EXPERIMENT:
            if snapshot.analyses:
                block = work_block(snapshot, A.RUN_FOLLOWUP)
                if block: return invalid(block)
            from autolab.experiment_design.validation import validate_design, evidence_references
            from autolab.experiment_design.context import build_context
            from autolab.experiment_design.models import ExperimentDesignError
            candidate = candidate_for_selection(snapshot, decision)
            if experiment and experiment.status in (s.ExperimentStatus.SELECTED, s.ExperimentStatus.PREREGISTERED):
                from autolab.analysis.persistence import reviewed_analysis
                if not reviewed_analysis(snapshot):
                    return invalid("An active selected ExperimentSpec already exists; do not preregister competing contracts simultaneously.")
            if not candidate or candidate.status != s.ExperimentStatus.PROPOSED:
                return invalid("SELECT_EXPERIMENT requires exactly one current proposed candidate ID.")
            hypothesis = selected_hypothesis(snapshot)
            if not hypothesis or (candidate.hypothesis_id, candidate.hypothesis_version) != (hypothesis.hypothesis_id, hypothesis.version):
                return invalid("Candidate must test the canonically selected exact hypothesis version.")
            review = latest_review(snapshot, s.ExperimentCandidate, candidate.candidate_id, candidate.version, "experiment")
            if not review or review.verdict != s.ReviewVerdict.PASS or review.reviewer_role != "critic":
                return invalid("Selection requires PASS review of the exact candidate version.")
            if any(e.event_type == "EXPERIMENT_SELECTED" and e.payload.get("candidate_id") == candidate.candidate_id for e in snapshot.events):
                return invalid("This candidate has already become a selected ExperimentSpec.")
            try:
                validate_design(candidate.design)
                evidence_references(candidate.model_dump(mode="json"), build_context(snapshot))
                from autolab.experiment_design.validation import spec_from_candidate
                from .adaptive import duplicate_of, replication_reason
                projected = spec_from_candidate(candidate, 'EXP_DUPLICATE_CHECK')
                if duplicate_of(snapshot, projected) and not replication_reason(projected):
                    return invalid('Scientifically duplicate completed experiment requires purpose=replication and replication_reason.')
            except (ValidationError, ExperimentDesignError):
                return invalid("Selected candidate lacks a valid preregisterable scientific design.")
        if consequential:
            if action == A.RUN_EXPERIMENT and current_run(snapshot) and (snapshot.authorized_scope or snapshot.charter.constraints.get('max_rounds')):
                return invalid('Adaptive repeat execution requires a fresh reviewed ExperimentSpec and fresh approval; current run already exists.')
            if not experiment or experiment.status in (s.ExperimentStatus.CANCELLED, s.ExperimentStatus.COMPLETED):
                return invalid("This action requires a selected active ExperimentSpec.")
            review = latest_review(snapshot, s.ExperimentSpec, experiment.experiment_id, experiment.version)
            if not review or review.verdict != s.ReviewVerdict.PASS:
                return invalid("Consequential work requires a PASS review of the exact ExperimentSpec version.")
            assessment = current_assessment(snapshot, experiment)
            if assessment is None:
                return ValidationResult(status=V.NEEDS_HUMAN_APPROVAL,
                    reasons=["A current feasibility assessment and exact-version human approval are required."])
            if assessment.blockers or assessment.status == "BLOCKED":
                return invalid("Execution feasibility is BLOCKED: " + "; ".join(assessment.blockers))
            if assessment.user_input_required or assessment.status == "NEEDS_USER_INPUT":
                return invalid("Required feasibility inputs remain unresolved.")
            approval_action = A.PREPARE_RESOURCES if action == A.COLLECT_MORE_DATA else action
            scope = approval_for(snapshot, approval_action)
            if scope is None:
                return ValidationResult(status=V.NEEDS_HUMAN_APPROVAL, reasons=["A scoped human approval for this exact experiment/action is required."])
            # The persisted assessment refines execution estimates without
            # mutating the scientific contract. Unknowns stay unknown; explicit
            # human caps bound eligibility, not an invented cost/runtime value.
            cost = assessment.cost.estimate_usd.maximum
            duration = assessment.runtime_minutes.maximum
            if cost is None:
                cost = scope.max_cost_usd
            if duration is None:
                duration = scope.max_runtime_minutes
            if cost > budget.remaining_budget_usd or cost > scope.max_cost_usd:
                return ValidationResult(status=V.BUDGET_BLOCKED, reasons=["Known experiment cost exceeds remaining budget or approved cost envelope."])
            if duration > scope.max_runtime_minutes or (time.remaining_minutes is not None and duration > time.remaining_minutes):
                return ValidationResult(status=V.TIME_BLOCKED, reasons=["Known runtime exceeds remaining time or approved runtime envelope."])
            if action == A.PREPARE_RESOURCES and target == "readiness" and not any(
                r.experiment_id == experiment.experiment_id and r.experiment_version == experiment.version for r in snapshot.resources):
                return invalid("Readiness audit requires prepared resources.")
            if action in (A.IMPLEMENT_EXPERIMENT, A.RUN_EXPERIMENT) and not readiness_passes(snapshot):
                return invalid("Implementation/execution requires a current PASS at all four readiness gates.")
            if action == A.IMPLEMENT_EXPERIMENT and target == "code_auditor" and not current_implementation(snapshot):
                return invalid("Code audit requires an implementation.")
            if action == A.RUN_EXPERIMENT and not implementation_passes(snapshot):
                return invalid("RUN_EXPERIMENT requires current exact implementation/code/dependency pins, independent PASS code review, and PASS deterministic tests.")
        if action == A.ANALYZE_RESULT:
            run = current_run(snapshot)
            from autolab.runtime.persistence import valid_result
            if not valid_result(snapshot, run):
                return invalid("ANALYZE_RESULT requires a completed, integrity-verified current run with raw outputs and every preregistered run-scoped metric.")
            from autolab.analysis.result_summary import evidence_pins
            from autolab.analysis.models import AnalysisError
            try: evidence_pins(snapshot, run)
            except AnalysisError:
                return invalid("ANALYZE_RESULT requires the current exact hypothesis and scientific contract.")
            if target == "critic":
                from autolab.analysis.persistence import analysis_current
                if not analysis_current(snapshot, current_analysis(snapshot)):
                    return invalid("Analysis critique requires a current exact ScientificAnalysis.")
        if action == A.RUN_FOLLOWUP:
            from .adaptive import hypothesis_disposition
            if not hypothesis or hypothesis_disposition(snapshot, hypothesis) == 'HYPOTHESIS_REJECTED':
                return invalid('Follow-up requires a current non-rejected hypothesis.')
            analysis = current_analysis(snapshot)
            if not analysis:
                return invalid("RUN_FOLLOWUP routes to new experiment design and requires prior analysis.")
            from autolab.analysis.persistence import reviewed_analysis
            if not reviewed_analysis(snapshot, analysis):
                return invalid("Follow-up design requires completed post-result critique.")
        return ValidationResult(status=V.VALID)

    def legal_actions(self, snapshot: ProjectSnapshot, *, now: datetime | None = None) -> list[A]:
        budget = calculate_budget(snapshot)
        legal = []
        for action in A:
            targets = self.roles.action_targets[action] or (None,)
            # Availability advertises a selectable PASS candidate without
            # choosing one for PI. The actual decision must identify its choice.
            selectable = [h for h in latest_versions(snapshot.hypotheses, "hypothesis_id")
                          if h.status != s.HypothesisStatus.REJECTED and (review := latest_review(
                              snapshot, s.Hypothesis, h.hypothesis_id, h.version)) and review.verdict == s.ReviewVerdict.PASS]
            context_ids = [selectable[0].hypothesis_id] if action == A.DESIGN_EXPERIMENT and selectable else []
            if action == A.SELECT_EXPERIMENT:
                candidates = [c for c in latest_versions(snapshot.candidates, "candidate_id")
                    if c.status == s.ExperimentStatus.PROPOSED and (review := latest_review(
                        snapshot, s.ExperimentCandidate, c.candidate_id, c.version, "experiment")) and review.verdict == s.ReviewVerdict.PASS]
                # Probe availability without selecting for PI. Check each candidate
                # because the first may belong to an earlier selected hypothesis.
                if any(self.validate(s.NextDecision(decision_id="DEC_POLICY_CHECK", project_id=snapshot.charter.project_id,
                    action=action, target_agent="planner", reason="Selection availability check",
                    required_context_ids=[c.candidate_id], remaining_budget_usd=budget.remaining_budget_usd), snapshot, now=now).valid for c in candidates):
                    legal.append(action)
                continue
            if any(self.validate(s.NextDecision(decision_id="DEC_POLICY_CHECK", project_id=snapshot.charter.project_id,
                       action=action, target_agent=target, reason="Deterministic availability check.",
                       required_context_ids=context_ids,
                       remaining_budget_usd=budget.remaining_budget_usd), snapshot, now=now).valid for target in targets):
                legal.append(action)
        return legal
