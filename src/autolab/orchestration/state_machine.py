"""Derived control state and gate facts. Scientific state lives in the ledger."""
import hashlib
from pydantic import ValidationError
from autolab import schemas as s
from .models import ApprovalScope, ControlStage as C, ProjectSnapshot


def charter_fingerprint(charter: s.ResearchCharter) -> str:
    return hashlib.sha256(charter.model_dump_json().encode()).hexdigest()


def latest_versions(records, id_field):
    latest = {}
    for record in records:
        identifier = getattr(record, id_field)
        if identifier not in latest or record.version > latest[identifier].version:
            latest[identifier] = record
    return list(latest.values())


def selected_experiment(snapshot: ProjectSnapshot):
    for event in reversed(snapshot.events):
        if event.event_type == "EXPERIMENT_SELECTED":
            identifier = event.payload.get("experiment_id", event.target_id)
            version = event.payload.get("version", 1)
            return next((e for e in snapshot.experiments if e.experiment_id == identifier and e.version == version), None)
    versions = latest_versions(snapshot.experiments, "experiment_id")
    eligible = [e for e in versions if e.status in (s.ExperimentStatus.SELECTED, s.ExperimentStatus.PREREGISTERED)]
    return eligible[0] if len(eligible) == 1 else None


def selected_hypothesis(snapshot: ProjectSnapshot):
    for event in reversed(snapshot.events):
        if event.event_type == "HYPOTHESIS_SELECTED":
            identifier = event.payload.get("hypothesis_id", event.target_id)
            version = event.payload.get("version", 1)
            return next((h for h in snapshot.hypotheses if h.hypothesis_id == identifier and h.version == version), None)
    experiment = selected_experiment(snapshot)
    if experiment:
        return next((h for h in snapshot.hypotheses if h.hypothesis_id == experiment.hypothesis_id
                     and h.version == experiment.hypothesis_version), None)
    latest = latest_versions(snapshot.hypotheses, "hypothesis_id")
    accepted = [h for h in latest if h.status == s.HypothesisStatus.ACCEPTED]
    return accepted[0] if len(accepted) == 1 else None


def hypothesis_for_decision(snapshot, decision):
    """An explicit context ID lets PI choose among exact latest proposals.

    DESIGN_EXPERIMENT selection is persisted by Orchestrator as the existing
    HYPOTHESIS_SELECTED event, atomically with the validated decision.
    """
    if decision.action == s.PlannerAction.DESIGN_EXPERIMENT and decision.target_agent == "experiment_designer":
        latest = latest_versions(snapshot.hypotheses, "hypothesis_id")
        explicit = [h for h in latest if h.hypothesis_id in decision.required_context_ids]
        if len(explicit) > 1:
            return None
        if explicit:
            return explicit[0]
    return selected_hypothesis(snapshot)


def candidate_for_selection(snapshot, decision):
    candidates = latest_versions(snapshot.candidates, "candidate_id")
    explicit = [c for c in candidates if c.candidate_id in decision.required_context_ids]
    return explicit[0] if len(explicit) == 1 else None


def latest_review(snapshot, model, identifier, version=1, review_type=None):
    direct = next((r for r in reversed(snapshot.reviews)
                 if r.target_type in (model.__name__, {s.Hypothesis: "hypotheses", s.ExperimentCandidate: "experiment_candidates", s.ExperimentSpec: "experiments",
                     s.ImplementationRecord: "implementations", s.ScientificAnalysis: "analyses"}[model])
                 and r.target_id == identifier and r.target_version == version
                 and (review_type is None or r.review_type == review_type)), None)
    if direct is not None or model != s.ExperimentSpec or review_type not in (None, "experiment"):
        return direct
    # A selected spec is an exact deterministic projection of a reviewed
    # candidate. Reuse its REAL review only while every scientific field matches.
    # No synthetic review is created or falsely attributed to the Critic. An
    # amendment or direct spec review supersedes this equivalence.
    event = next((e for e in reversed(snapshot.events) if e.event_type == "EXPERIMENT_SPEC_CREATED"
        and e.actor == "orchestrator" and e.payload.get("experiment_id") == identifier
        and e.payload.get("version") == version), None)
    if event is None:
        return None
    candidate = next((c for c in snapshot.candidates if c.candidate_id == event.payload.get("candidate_id")
        and c.version == event.payload.get("candidate_version")), None)
    spec = next((e for e in snapshot.experiments if e.experiment_id == identifier and e.version == version), None)
    if candidate is None or spec is None:
        return None
    from autolab.experiment_design.validation import spec_from_candidate
    try:
        projection = spec_from_candidate(candidate, identifier)
    except (ValueError, RuntimeError):
        return None
    ignored = {"created_at", "experiment_id", "version", "status"}
    if spec.model_dump(exclude=ignored) != projection.model_dump(exclude=ignored):
        return None
    review = latest_review(snapshot, s.ExperimentCandidate, candidate.candidate_id, candidate.version, "experiment")
    return review if review and review.reviewer_role == "critic" else None


def current_readiness(snapshot):
    experiment = selected_experiment(snapshot)
    return next((r for r in reversed(snapshot.readiness) if experiment and r.experiment_id == experiment.experiment_id
                 and r.experiment_version == experiment.version), None)


def readiness_passes(snapshot):
    report = current_readiness(snapshot)
    if not report or report.verdict != s.ReadinessVerdict.PASS or report.failed_checks:
        return False
    if not all((report.resource_readiness, report.technical_readiness, report.scientific_readiness, report.quality_readiness)):
        return False
    from autolab.preparation.manifest import readiness_current
    return readiness_current(snapshot, report)



def current_implementation(snapshot):
    experiment = selected_experiment(snapshot)
    return next((i for i in reversed(snapshot.implementations) if experiment and i.experiment_id == experiment.experiment_id
                 and i.experiment_version == experiment.version), None)


def current_run(snapshot):
    experiment = selected_experiment(snapshot)
    return next((r for r in reversed(snapshot.runs) if experiment and r.experiment_id == experiment.experiment_id
                 and r.experiment_version == experiment.version), None)


def current_analysis(snapshot):
    run = current_run(snapshot)
    return next((a for a in reversed(snapshot.analyses) if run and a.run_id == run.run_id), None)


def implementation_passes(snapshot):
    implementation = current_implementation(snapshot)
    if not implementation: return False
    from autolab.implementation.persistence import audited_implementation_passes
    return audited_implementation_passes(snapshot, implementation)


def pending_approval(snapshot):
    from autolab.feasibility.persistence import HUMAN_ACTORS, HUMAN_EVENTS, packet_pending
    packet = packet_pending(snapshot)
    if packet:
        return packet
    request = next((d for d in reversed(snapshot.decisions)
                    if d.action == s.PlannerAction.REQUEST_HUMAN_APPROVAL), None)
    if request and not any(e.actor in HUMAN_ACTORS and e.event_type in HUMAN_EVENTS
                          and e.payload.get("decision_id") == request.decision_id
                          and e.created_at >= request.created_at for e in snapshot.events):
        return request
    return None


def approval_for(snapshot, action):
    from autolab.feasibility.models import FeasibilityStatus as F
    from autolab.feasibility.persistence import (HUMAN_ACTORS, HUMAN_EVENTS, assessment_fingerprint,
        current_assessment, current_packet, selected_is_current, spec_fingerprint)
    if pending_approval(snapshot):
        return None
    experiment = selected_experiment(snapshot)
    if not selected_is_current(snapshot, experiment):
        return None
    assessment = current_assessment(snapshot, experiment)
    if (not assessment or assessment.status in (F.BLOCKED, F.NEEDS_USER_INPUT)
        or assessment.blockers or assessment.user_input_required):
        return None
    implementation = current_implementation(snapshot)
    # The latest human approval response for this exact spec supersedes prior
    # approval. A request alone never grants authority; Planner cannot approve.
    for event in reversed(snapshot.events):
        if event.actor not in HUMAN_ACTORS or event.event_type not in HUMAN_EVENTS or event.project_id != snapshot.charter.project_id:
            continue
        if event.payload.get("experiment_id") != experiment.experiment_id or event.payload.get("experiment_version", 1) != experiment.version:
            continue
        if event.event_type != "HUMAN_APPROVED":
            return None
        try:
            scope = ApprovalScope.model_validate(event.payload)
        except ValidationError:
            return None
        if (scope.assessment_id != assessment.assessment_id or scope.assessment_version != assessment.version
            or scope.assessment_fingerprint != assessment_fingerprint(assessment)
            or scope.spec_fingerprint != spec_fingerprint(experiment)
            or assessment.has_unknown_estimates and not scope.acknowledged_unknowns):
            return None
        packet = current_packet(snapshot, experiment)
        if (packet and (scope.packet_id != packet.packet_id or packet.assessment != assessment)
            or packet is None and scope.packet_id is not None):
            return None
        if any(e.event_type=='RESOURCE_PREPARATION_BLOCKED' and e.actor=='preparation'
            and e.target_id==experiment.experiment_id and e.payload.get('experiment_version')==experiment.version
            and e.payload.get('status')=='NEEDS_REAPPROVAL' and (e.created_at>event.created_at or e.created_at>=assessment.created_at) for e in snapshot.events):
            return None
        if action not in scope.approved_actions:
            return None
        if action == s.PlannerAction.RUN_EXPERIMENT and (not implementation or scope.implementation_id != implementation.implementation_id):
            return None
        return scope
    return None


def derive_control_state(snapshot: ProjectSnapshot) -> C:
    status = snapshot.charter.status
    if status in (s.ProjectStatus.COMPLETED, s.ProjectStatus.STOPPED):
        return C.COMPLETED
    # Explicit control events overlay immutable charter status. A resume cannot
    # override a terminal STOP or a charter originally marked completed.
    lifecycle = [e for e in snapshot.events if e.event_type in (
        "PROJECT_PAUSED", "PROJECT_RESUMED", "PROJECT_BLOCKED", "PROJECT_UNBLOCKED")]
    if any(d.action == s.PlannerAction.STOP for d in snapshot.decisions):
        return C.COMPLETED
    if any(e.event_type == 'HUMAN_STOPPED' and e.actor in ('human', 'test-human')
           for e in snapshot.events):
        return C.COMPLETED
    paused, blocked = status == s.ProjectStatus.PAUSED, False
    for event in lifecycle:
        if event.event_type == "PROJECT_PAUSED":
            paused = True
        elif event.event_type == "PROJECT_RESUMED":
            paused = False
        elif event.event_type == "PROJECT_BLOCKED":
            blocked = True
        elif event.event_type == "PROJECT_UNBLOCKED":
            blocked = False
    if paused:
        return C.PAUSED
    if blocked:
        return C.BLOCKED
    if pending_approval(snapshot):
        from autolab.feasibility.persistence import current_assessment
        assessment = current_assessment(snapshot)
        if assessment and assessment.status == "BLOCKED":
            return C.BLOCKED
        return C.AWAITING_HUMAN_APPROVAL
    from autolab.runtime.persistence import active_run, valid_result
    if active_run(snapshot):
        return C.RUNNING
    run = current_run(snapshot)
    if run:
        if run.status == s.RunStatus.RUNNING:
            return C.RUNNING
        if run.status in (s.RunStatus.FAILED, s.RunStatus.TIMED_OUT, s.RunStatus.CANCELLED):
            return C.ADAPTIVE_DECISION
        if run.status == s.RunStatus.COMPLETED:
            if not valid_result(snapshot, run):
                return C.ADAPTIVE_DECISION
            from autolab.analysis.result_summary import evidence_pins
            from autolab.analysis.models import AnalysisError
            try: evidence_pins(snapshot, run)
            except AnalysisError: return C.ADAPTIVE_DECISION
            analysis = current_analysis(snapshot)
            if not analysis:
                return C.ANALYSIS
            from autolab.analysis.persistence import analysis_current, reviewed_analysis
            if not analysis_current(snapshot, analysis): return C.ADAPTIVE_DECISION
            review = latest_review(snapshot, s.ScientificAnalysis, analysis.analysis_id, analysis.version, 'analysis')
            if reviewed_analysis(snapshot, analysis): return C.ADAPTIVE_DECISION
            if review and review.verdict in (s.ReviewVerdict.REJECT, s.ReviewVerdict.REVISE):
                return C.ANALYSIS if review.verdict == s.ReviewVerdict.REVISE and analysis.version == 1 else C.ADAPTIVE_DECISION
            return C.ANALYSIS_REVIEW
    experiment = selected_experiment(snapshot)
    if experiment:
        review = latest_review(snapshot, s.ExperimentSpec, experiment.experiment_id, experiment.version)
        if not review or review.verdict != s.ReviewVerdict.PASS:
            return C.EXPERIMENT_REVIEW
        from autolab.feasibility.persistence import current_assessment, human_event
        assessment = current_assessment(snapshot, experiment)
        if assessment and assessment.status == "BLOCKED":
            return C.BLOCKED
        response = human_event(snapshot, experiment)
        if response and response.event_type in ("HUMAN_REJECTED", "HUMAN_MODIFY", "HUMAN_MODIFICATION_REQUESTED"):
            return C.ADAPTIVE_DECISION
        readiness = current_readiness(snapshot)
        if readiness and readiness.verdict == s.ReadinessVerdict.BLOCK:
            return C.ADAPTIVE_DECISION
        implementation = current_implementation(snapshot)
        if readiness_passes(snapshot):
            if not implementation:
                return C.IMPLEMENTATION if approval_for(snapshot, s.PlannerAction.IMPLEMENT_EXPERIMENT) else C.AWAITING_HUMAN_APPROVAL
            if not implementation_passes(snapshot):
                code_review = latest_review(snapshot, s.ImplementationRecord, implementation.implementation_id, review_type="code")
                if code_review and code_review.verdict in (s.ReviewVerdict.BLOCK, s.ReviewVerdict.REJECT):
                    return C.ADAPTIVE_DECISION
                if any(e.event_type == 'IMPLEMENTATION_BLOCKED' and e.actor == 'implementation_validator'
                       and e.target_id == implementation.implementation_id for e in snapshot.events):
                    return C.ADAPTIVE_DECISION
                if code_review and code_review.verdict == s.ReviewVerdict.REVISE:
                    return C.IMPLEMENTATION
                return C.CODE_REVIEW
            return C.READY_TO_RUN if approval_for(snapshot, s.PlannerAction.RUN_EXPERIMENT) else C.AWAITING_HUMAN_APPROVAL
        if not approval_for(snapshot, s.PlannerAction.PREPARE_RESOURCES):
            return C.AWAITING_HUMAN_APPROVAL
        resources = [r for r in snapshot.resources if r.experiment_id == experiment.experiment_id and r.experiment_version == experiment.version]
        return C.READINESS_REVIEW if resources and not readiness else C.RESOURCE_PREPARATION
    hypothesis = selected_hypothesis(snapshot)
    if hypothesis:
        review = latest_review(snapshot, s.Hypothesis, hypothesis.hypothesis_id, hypothesis.version)
        return C.EXPERIMENT_DESIGN if review and review.verdict == s.ReviewVerdict.PASS else C.HYPOTHESIS_REVIEW
    if snapshot.hypotheses:
        return C.HYPOTHESIS_REVIEW
    if snapshot.evidence:
        return C.HYPOTHESIS_FORMATION
    return C.EVIDENCE_GATHERING if snapshot.decisions and snapshot.decisions[-1].action == s.PlannerAction.GATHER_EVIDENCE else C.INITIALIZED
