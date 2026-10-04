"""One adaptive decision cycle. Future specialists plug into returned routes."""
import logging
from typing import Protocol

from pydantic import ValidationError
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.planner.service import PlannerOutputError, runtime_metadata
from .budget import calculate_budget
from .context_builder import ContextBuilder
from .decision_validator import DecisionValidator
from .models import PlannerContext, RoutingDecision
from .snapshot import load_snapshot
from .state_machine import derive_control_state, hypothesis_for_decision, candidate_for_selection, latest_review, latest_versions

log = logging.getLogger(__name__)


class IllegalDecisionError(RuntimeError):
    pass


class PlannerClient(Protocol):
    async def propose(self, context: PlannerContext, decision_id: str, feedback: dict | None = None) -> str: ...


class Orchestrator:
    def __init__(self, ledger: ResearchLedger, planner: PlannerClient,
                 validator: DecisionValidator | None = None, context_builder: ContextBuilder | None = None):
        self.ledger = ledger
        self.planner = planner
        self.validator = validator or DecisionValidator()
        self.context_builder = context_builder or ContextBuilder(validator=self.validator)

    async def execute_analysis(self, route: RoutingDecision, pipeline=None):
        """One persisted analysis route; returns Planner control without next-action dispatch."""
        from autolab.analysis.service import AnalysisService
        decision=self.ledger.get(s.NextDecision,route.decision_id)
        if not decision or decision.action!=s.PlannerAction.ANALYZE_RESULT or route.action!=decision.action or route.target_role!=decision.target_agent:
            raise IllegalDecisionError('Dispatch requires matching persisted ANALYZE_RESULT route')
        snapshot=load_snapshot(self.ledger,decision.project_id)
        if not snapshot.decisions or snapshot.decisions[-1]!=decision:
            raise IllegalDecisionError('Analysis route superseded')
        if any(e.event_type=='ANALYSIS_DISPATCHED' and e.payload.get('decision_id')==decision.decision_id for e in snapshot.events):
            raise IllegalDecisionError('Analysis route already dispatched; no repeated model workflow')
        workflow=pipeline if pipeline is not None else AnalysisService(self.ledger)
        if workflow.ledger is not self.ledger: raise IllegalDecisionError('Analysis must share orchestrator ledger')
        def check():
            fresh=load_snapshot(self.ledger,decision.project_id)
            if fresh!=snapshot or not self.validator.validate(decision,fresh).valid:
                raise IllegalDecisionError('Analysis route no longer legal')
        self.ledger.add_many([s.EventRecord(event_id=self.ledger.next_id('EVENT'),project_id=decision.project_id,
            event_type='ANALYSIS_DISPATCHED',actor='orchestrator',target_type='decisions',target_id=decision.decision_id,
            summary='Bounded analysis/critique dispatch; no Phase 12 execution',payload={'decision_id':decision.decision_id})],check=check)
        result=await workflow.run(decision.project_id,critique_only=decision.target_agent=='critic')
        self.ledger.add_event(s.EventRecord(event_id=self.ledger.next_id('EVENT'),project_id=decision.project_id,
            event_type='SPECIALIST_COMPLETED',actor='orchestrator',target_type='decisions',target_id=decision.decision_id,
            summary='Reviewed interpretation returned Planner control; next scientific action not executed',
            payload={'decision_id':decision.decision_id,'role':decision.target_agent,**result.model_dump(mode='json')}))
        return result

    async def execute_runtime(self, route: RoutingDecision, runtime, **limits):
        """Dispatch one persisted legal run; return PI control, never analysis."""
        decision=self.ledger.get(s.NextDecision,route.decision_id)
        if not decision or decision.action!=s.PlannerAction.RUN_EXPERIMENT or route.action!=decision.action or route.target_role!='experiment_runner':
            raise IllegalDecisionError('Dispatch requires matching persisted RUN_EXPERIMENT route')
        snapshot=load_snapshot(self.ledger,decision.project_id)
        if not snapshot.decisions or snapshot.decisions[-1].decision_id!=decision.decision_id:
            raise IllegalDecisionError('Runtime route superseded')
        if any(e.payload.get('decision_id')==decision.decision_id and e.event_type in ('RUNTIME_DISPATCHED','SPECIALIST_COMPLETED') for e in snapshot.events):
            raise IllegalDecisionError('Runtime route already dispatched; never silently rerun')
        if runtime.ledger is not self.ledger: raise IllegalDecisionError('Runtime must share orchestrator ledger')
        def check():
            fresh=load_snapshot(self.ledger,decision.project_id)
            valid=self.validator.validate(decision,fresh)
            if fresh!=snapshot or not valid.valid: raise IllegalDecisionError('Runtime route no longer legal')
        self.ledger.add_many([s.EventRecord(event_id=self.ledger.next_id('EVENT'),project_id=decision.project_id,
            event_type='RUNTIME_DISPATCHED',actor='orchestrator',target_type='decisions',target_id=decision.decision_id,
            summary='Dispatch one deterministic attempt',payload={'decision_id':decision.decision_id})],check=check)
        result=await runtime.run(decision.project_id,**limits)
        self.ledger.add_event(s.EventRecord(event_id=self.ledger.next_id('EVENT'),project_id=decision.project_id,
            event_type='SPECIALIST_COMPLETED',actor='orchestrator',target_type='decisions',target_id=decision.decision_id,
            summary='Deterministic runtime returned Planner control; no Phase 11 dispatch',
            payload={'decision_id':decision.decision_id,'role':'experiment_runner','run_id':result.run_id,'status':result.status.value}))
        return result

    async def execute_implementation(self, route: RoutingDecision, pipeline=None):
        """Phase 9 ends at the next Planner routing boundary; never dispatch run."""
        from autolab.implementation.service import ImplementationService
        decision = self.ledger.get(s.NextDecision, route.decision_id)
        if (not decision or decision.action != s.PlannerAction.IMPLEMENT_EXPERIMENT
            or route.action != decision.action or route.target_role != decision.target_agent
            or decision.target_agent not in ('implementer', 'code_auditor')):
            raise IllegalDecisionError('Dispatch requires matching persisted IMPLEMENT_EXPERIMENT route')
        snapshot = load_snapshot(self.ledger, decision.project_id)
        if snapshot.decisions[-1].decision_id != decision.decision_id:
            raise IllegalDecisionError('Implementation route superseded')
        if any(e.event_type == 'SPECIALIST_COMPLETED' and e.payload.get('decision_id') == decision.decision_id for e in snapshot.events):
            raise IllegalDecisionError('Implementation route already completed')
        valid = self.validator.validate(decision, snapshot)
        if not valid.valid: raise IllegalDecisionError('Implementation route no longer legal: ' + '; '.join(valid.reasons))
        workflow = pipeline if pipeline is not None else ImplementationService(self.ledger)
        if workflow.ledger is not self.ledger: raise IllegalDecisionError('Implementation must share orchestrator ledger')
        result = await workflow.run(decision.project_id, audit_only=decision.target_agent == 'code_auditor')
        self.ledger.add_event(s.EventRecord(event_id=self.ledger.next_id('EVENT'), project_id=decision.project_id,
            event_type='SPECIALIST_COMPLETED', actor='orchestrator', target_type='decisions', target_id=decision.decision_id,
            summary='Implementation and independent code audit returned control to Planner; Phase 10 not executed',
            payload={'decision_id': decision.decision_id, 'role': decision.target_agent, **result.model_dump(mode='json')}))
        return result

    async def execute_preparation(self, route: RoutingDecision, pipeline=None, auditor=None):
        """Execute approved preparation and independent readiness, then return to PI.

        No implementation, runner or subsequent Planner action is dispatched here.
        """
        from autolab.preparation.service import PreparationService
        from autolab.readiness.service import ReadinessService
        decision = self.ledger.get(s.NextDecision, route.decision_id)
        if (decision is None or decision.action != s.PlannerAction.PREPARE_RESOURCES
            or decision.target_agent not in ("preparation", "readiness")
            or route.action != decision.action or route.target_role != decision.target_agent):
            raise IllegalDecisionError("Dispatch requires a matching persisted PREPARE_RESOURCES route")
        snapshot = load_snapshot(self.ledger, decision.project_id)
        if not snapshot.decisions or snapshot.decisions[-1].decision_id != decision.decision_id:
            raise IllegalDecisionError("Preparation route was superseded")
        if any(e.event_type == "SPECIALIST_COMPLETED" and e.payload.get("decision_id") == decision.decision_id for e in snapshot.events):
            raise IllegalDecisionError("Preparation route already completed")
        check = self.validator.validate(decision, snapshot)
        if not check.valid:
            raise IllegalDecisionError("Preparation route no longer legal: " + "; ".join(check.reasons))
        workflow = pipeline if pipeline is not None else PreparationService(self.ledger)
        audit = auditor if auditor is not None else ReadinessService(self.ledger)
        if workflow.ledger is not self.ledger or audit.ledger is not self.ledger:
            raise IllegalDecisionError("Preparation/readiness must share the orchestrator ledger")
        result = await audit.audit(decision.project_id) if route.target_role == "readiness" else await workflow.run(decision.project_id, audit)
        self.ledger.add_event(s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=decision.project_id,
            event_type="SPECIALIST_COMPLETED", actor="orchestrator", target_type="decisions", target_id=decision.decision_id,
            summary="Preparation and independent readiness returned control to Planner; no implementation executed",
            payload={"decision_id": decision.decision_id, "role": decision.target_agent,
                     "status": getattr(result, "status", getattr(result, "verdict", "UNKNOWN")),
                     "readiness_id": getattr(result, "readiness_id", None)}))
        return result

    async def execute_experiment_design(self, route: RoutingDecision, pipeline=None):
        from autolab.experiment_design.service import ExperimentDesignPipeline
        decision = self.ledger.get(s.NextDecision, route.decision_id)
        if decision:
            from .adaptive import decision_receipt
            prior = load_snapshot(self.ledger, decision.project_id)
            if decision_receipt(prior, decision.decision_id) and not any(e.event_type == 'ADAPTIVE_DISPATCHED'
                and e.payload.get('decision_id') == decision.decision_id for e in prior.events):
                return await self.execute_adaptive(route, services={'design': pipeline} if pipeline else None)
        if (decision is None or decision.action not in (s.PlannerAction.DESIGN_EXPERIMENT, s.PlannerAction.RUN_FOLLOWUP)
            or decision.target_agent != "experiment_designer" or route.action != decision.action
            or route.target_role != decision.target_agent):
            raise IllegalDecisionError("Dispatch requires a matching persisted DESIGN_EXPERIMENT route")
        snapshot = load_snapshot(self.ledger, decision.project_id)
        if not snapshot.decisions or snapshot.decisions[-1].decision_id != decision.decision_id:
            raise IllegalDecisionError("Experiment design route was superseded")
        if any(e.event_type == "SPECIALIST_COMPLETED" and e.payload.get("decision_id") == decision.decision_id for e in snapshot.events):
            raise IllegalDecisionError("Experiment design route already completed")
        check = self.validator.validate(decision, snapshot)
        if not check.valid:
            raise IllegalDecisionError("Experiment design route no longer legal: " + "; ".join(check.reasons))
        workflow = pipeline if pipeline is not None else ExperimentDesignPipeline(self.ledger)
        if workflow.ledger is not self.ledger:
            raise IllegalDecisionError("Experiment design must share the orchestrator ledger")
        result = await workflow.generate(decision.project_id)
        self.ledger.add_event(s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=decision.project_id,
            event_type="SPECIALIST_COMPLETED", actor="orchestrator", target_type="decisions", target_id=decision.decision_id,
            summary="Experimental Scientist and existing Scientific Critic returned control to Planner",
            payload={"decision_id": decision.decision_id, "role": "experiment_designer",
                     "candidate_ids": result.candidate_ids, "review_ids": result.review_ids}))
        return result

    async def execute_hypotheses(self, route: RoutingDecision, pipeline=None):
        """Execute the registered hypothesis workflow, then return control."""
        from autolab.hypotheses.service import HypothesisPipeline
        decision = self.ledger.get(s.NextDecision, route.decision_id)
        if decision:
            from .adaptive import decision_receipt
            prior = load_snapshot(self.ledger, decision.project_id)
            if decision_receipt(prior, decision.decision_id) and not any(e.event_type == 'ADAPTIVE_DISPATCHED'
                and e.payload.get('decision_id') == decision.decision_id for e in prior.events):
                return await self.execute_adaptive(route, services={'hypothesis': pipeline} if pipeline else None)
        if decision is None or decision.action != s.PlannerAction.GENERATE_HYPOTHESES:
            raise IllegalDecisionError("Dispatch requires a persisted GENERATE_HYPOTHESES decision")
        if decision.target_agent != "hypothesis" or route.action != decision.action or route.target_role != "hypothesis":
            raise IllegalDecisionError("Route does not match the persisted hypothesis decision")
        snapshot = load_snapshot(self.ledger, decision.project_id)
        if not snapshot.decisions or snapshot.decisions[-1].decision_id != decision.decision_id:
            raise IllegalDecisionError("Hypothesis route was superseded by a newer decision")
        if any(e.event_type == "SPECIALIST_COMPLETED" and e.payload.get("decision_id") == decision.decision_id for e in snapshot.events):
            raise IllegalDecisionError("Hypothesis route already completed; ask Planner for a new decision")
        valid = self.validator.validate(decision, snapshot)
        if not valid.valid:
            raise IllegalDecisionError("Hypothesis dispatch is no longer legal: " + "; ".join(valid.reasons))
        workflow = pipeline if pipeline is not None else HypothesisPipeline(self.ledger)
        if workflow.ledger is not self.ledger:
            raise IllegalDecisionError("Hypothesis workflow must share the orchestrator ledger")
        result = await workflow.generate(decision.project_id)
        self.ledger.add_event(s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=decision.project_id,
            event_type="SPECIALIST_COMPLETED", actor="orchestrator", target_type="decisions", target_id=decision.decision_id,
            summary="Hypothesis Scientist and Scientific Critic returned control to Planner",
            payload={"decision_id": decision.decision_id, "role": "hypothesis",
                     "hypothesis_ids": result.hypothesis_ids, "review_ids": result.review_ids}))
        return result

    async def execute_evidence(self, route: RoutingDecision, pipeline=None):
        """Dispatch only a persisted evidence route; caller chooses next cycle."""
        from autolab.literature.service import EvidencePipeline
        decision = self.ledger.get(s.NextDecision, route.decision_id)
        if decision:
            from .adaptive import decision_receipt
            prior = load_snapshot(self.ledger, decision.project_id)
            if decision_receipt(prior, decision.decision_id) and not any(e.event_type == 'ADAPTIVE_DISPATCHED'
                and e.payload.get('decision_id') == decision.decision_id for e in prior.events):
                return await self.execute_adaptive(route, services={'evidence': pipeline} if pipeline else None)
        if decision is None or decision.action not in (s.PlannerAction.GATHER_EVIDENCE, s.PlannerAction.COLLECT_MORE_DATA):
            raise IllegalDecisionError("Dispatch requires a persisted evidence decision")
        if decision.target_agent != "evidence" or route.action != decision.action or route.target_role != decision.target_agent:
            raise IllegalDecisionError("Route does not match the persisted evidence decision")
        snapshot = load_snapshot(self.ledger, decision.project_id)
        if not snapshot.decisions or snapshot.decisions[-1].decision_id != decision.decision_id:
            raise IllegalDecisionError("Evidence route has been superseded by a newer decision")
        if any(event.event_type == "SPECIALIST_COMPLETED" and event.payload.get("decision_id") == decision.decision_id for event in snapshot.events):
            raise IllegalDecisionError("Evidence route already completed; ask Planner for a new decision")
        valid = self.validator.validate(decision, snapshot)
        if not valid.valid:
            raise IllegalDecisionError("Evidence dispatch is no longer legal: " + "; ".join(valid.reasons))
        workflow = pipeline if pipeline is not None else EvidencePipeline(self.ledger)
        if workflow.ledger is not self.ledger:
            raise IllegalDecisionError("Evidence workflow must share the orchestrator ledger")
        result = await workflow.gather(decision.project_id)
        self.ledger.add_event(s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=decision.project_id,
            event_type="SPECIALIST_COMPLETED", actor="orchestrator", target_id=decision.decision_id, target_type="decisions",
            summary="Evidence specialist returned control to Planner", payload={"decision_id": decision.decision_id,
                "role": "evidence", "source_ids": result.source_ids, "evidence_ids": result.evidence_ids}))
        return result

    async def decide(self, project_id: str, *, max_repairs: int = 1) -> RoutingDecision:
        snapshot = load_snapshot(self.ledger, project_id)
        context = self.context_builder.build(snapshot)
        decision_id = self.ledger.next_id("DEC")
        feedback = None
        if max_repairs not in (0, 1): raise ValueError("Planner repair bound is 0 or 1")
        for attempt in range(1 + max_repairs):
            # Invocation failures propagate and do not trigger a blind retry.
            raw = await self.planner.propose(context, decision_id, feedback)
            try:
                proposed = s.NextDecision.model_validate_json(raw)
            except ValidationError:
                proposed = None
                result = None
                reasons = ["Return only strict JSON conforming to the supplied canonical NextDecision schema."]
            else:
                result = self.validator.validate(proposed, snapshot,
                    expected_decision_id=decision_id, expected_charter_fingerprint=context.charter_fingerprint)
                reasons = result.reasons
            if result is None or not result.valid:
                log.info("PLANNER_DECISION_REJECTED project=%s attempt=%d status=%s", project_id, attempt+1,
                         result.status.value if result else "INVALID_JSON")
                if attempt == max_repairs:
                    if proposed is not None and any('maximum research rounds' in x for x in reasons):
                        self.ledger.add_event(s.EventRecord(event_id=self.ledger.next_id('EVENT'), project_id=project_id,
                            event_type='ROUND_LIMIT_REACHED', actor='orchestrator', summary='Proposed additional work blocked by hard charter round limit',
                            payload={'proposed_decision': proposed.model_dump(mode='json'), 'reasons': reasons}))
                    error = PlannerOutputError if result is None else IllegalDecisionError
                    raise error("Planner proposal bound exhausted: " + "; ".join(reasons))
                # Avoid storing/logging huge invalid output. Context is unchanged
                # during the single repair attempt; failures are deterministic.
                feedback = {"previous_output": raw[:4000], "validation_errors": reasons, "attempts_remaining": 1}
                continue
            accepted = s.NextDecision.model_validate({**proposed.model_dump(), "created_at": s.utc_now(), "remaining_budget_usd": calculate_budget(snapshot).remaining_budget_usd})
            event = s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id,
                event_type="PLANNER_DECISION", actor="planner", target_type="decisions", target_id=decision_id,
                summary=f"Planner selected {accepted.action.value}: {accepted.reason[:240]}",
                payload={"decision_id": decision_id, "action": accepted.action.value,
                         "target_role": accepted.target_agent, "required_context_ids": accepted.required_context_ids,
                         **({"model_metadata": runtime_metadata(self.planner)} if runtime_metadata(self.planner) else {})})
            selection = []
            if accepted.action == s.PlannerAction.DESIGN_EXPERIMENT and accepted.target_agent == "experiment_designer":
                hypothesis = hypothesis_for_decision(snapshot, accepted)
                selection.append(s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id,
                    event_type="HYPOTHESIS_SELECTED", actor="planner", target_type="hypotheses", target_id=hypothesis.hypothesis_id,
                    summary="Planner selected an exact reviewed hypothesis version for future design",
                    payload={"hypothesis_id": hypothesis.hypothesis_id, "version": hypothesis.version,
                             "decision_id": accepted.decision_id, "reason": accepted.reason}))
            if accepted.action == s.PlannerAction.SELECT_EXPERIMENT:
                from autolab.experiment_design.validation import spec_from_candidate
                candidate = candidate_for_selection(snapshot, accepted)
                review = latest_review(snapshot, s.ExperimentCandidate, candidate.candidate_id, candidate.version, "experiment")
                experiment = spec_from_candidate(candidate, self.ledger.next_id("EXP"))
                provenance = {"experiment_id": experiment.experiment_id, "version": experiment.version,
                    "candidate_id": candidate.candidate_id, "candidate_version": candidate.version,
                    "hypothesis_id": candidate.hypothesis_id, "hypothesis_version": candidate.hypothesis_version,
                    "review_id": review.review_id, "decision_id": accepted.decision_id, "reason": accepted.reason}
                provenance["non_selected_candidate_ids"] = [c.candidate_id for c in latest_versions(snapshot.candidates, "candidate_id")
                    if c.hypothesis_id == candidate.hypothesis_id and c.hypothesis_version == candidate.hypothesis_version
                    and c.candidate_id != candidate.candidate_id]
                selection.extend([experiment,
                    s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id,
                        event_type="EXPERIMENT_SELECTED", actor="planner", target_type="experiments", target_id=experiment.experiment_id,
                        summary="Planner selected the reviewed candidate and exact scientific contract", payload=provenance),
                    s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id,
                        event_type="EXPERIMENT_SPEC_CREATED", actor="orchestrator", target_type="experiments", target_id=experiment.experiment_id,
                        summary="Canonical metrics and interpretation criteria preregistered before results", payload=provenance)])
            def recheck():
                fresh = load_snapshot(self.ledger, project_id)
                if fresh != snapshot and accepted.action != s.PlannerAction.STOP:
                    raise IllegalDecisionError("Research state changed before persistence; rebuild Planner context.")
                final = self.validator.validate(accepted, fresh, expected_decision_id=decision_id,
                    expected_charter_fingerprint=context.charter_fingerprint)
                if not final.valid:
                    raise IllegalDecisionError("Research state changed before persistence: " + "; ".join(final.reasons))
            # Final prerequisites/budget recheck and both inserts occur under a
            # single SQLite write lock. No accepted decision can lose its audit.
            from .adaptive import decision_events, source_links, decision_receipt
            if accepted.action == s.PlannerAction.SELECT_EXPERIMENT and snapshot.analyses:
                trigger = next((e for e in reversed(snapshot.events) if e.event_type == 'FOLLOWUP_REQUESTED'), None)
                for record in selection:
                    if isinstance(record, s.EventRecord):
                        record.payload.update({**(trigger.payload if trigger else {}), **source_links(snapshot),
                            'selection_decision_id': accepted.decision_id, 'followup_reason': trigger.payload.get('reason') if trigger else accepted.reason})
            adaptive_events = decision_events(self.ledger, snapshot, accepted, selection)
            self.ledger.add_many([accepted, event, *selection, *adaptive_events], check=recheck)
            if attempt:
                log.info("PLANNER_DECISION_REPAIRED project=%s decision=%s", project_id, decision_id)
            log.info("PLANNER_DECISION_ACCEPTED project=%s decision=%s action=%s target=%s", project_id,
                     decision_id, accepted.action.value, accepted.target_agent)
            state = derive_control_state(load_snapshot(self.ledger, project_id))
            return RoutingDecision(decision_id=decision_id, action=accepted.action, target_role=accepted.target_agent,
                reason=accepted.reason, context_requirements=accepted.required_context_ids, control_state=state)
        raise AssertionError("Bounded planner loop unexpectedly exhausted.")

    async def execute_adaptive(self, route: RoutingDecision, *, services=None):
        """Dispatch one exact PI choice. Interrupted dispatches require reconciliation."""
        from .adaptive import decision_receipt, work_block, rounds, round_count, source_links
        services = services or {}
        decision = self.ledger.get(s.NextDecision, route.decision_id)
        if not decision or (route.action, route.target_role) != (decision.action, decision.target_agent):
            raise IllegalDecisionError('Adaptive route must match persisted NextDecision')
        before = load_snapshot(self.ledger, decision.project_id)
        if not before.decisions or before.decisions[-1] != decision:
            raise IllegalDecisionError('Adaptive route superseded')
        if any(e.event_type == 'ADAPTIVE_DISPATCHED' and e.payload.get('decision_id') == decision.decision_id for e in before.events):
            raise IllegalDecisionError('Adaptive dispatch already started; reconcile incomplete work explicitly')
        valid = self.validator.validate(decision, before)
        if not valid.valid:
            raise IllegalDecisionError('; '.join(valid.reasons))
        def event(kind, payload, summary):
            return s.EventRecord(event_id=self.ledger.next_id('EVENT'), project_id=decision.project_id,
                event_type=kind, actor='orchestrator', target_type='decisions', target_id=decision.decision_id,
                summary=summary, payload={'decision_id': decision.decision_id, **payload})
        records = [event('ADAPTIVE_DISPATCHED', {}, 'Once-only dispatch of validated Planner action')]
        starts = rounds(before)
        active = starts[-1] if starts else None
        completed = active and any(e.event_type == 'RESEARCH_ROUND_COMPLETED' and e.payload.get('round_id') == active.payload['round_id'] for e in before.events)
        from .adaptive import NEW_WORK
        round_id = active.payload['round_id'] if active else 'ROUND_0001'
        if decision.action in NEW_WORK and (not active or completed):
            index = round_count(before) + 1
            round_id = f'ROUND_{index:04d}'
            records.append(event('RESEARCH_ROUND_STARTED', {'round_id': round_id, 'index': index,
                'parent_round': active.payload['round_id'] if active else ('ROUND_0001' if before.runs else None),
                'trigger_decision': decision.decision_id, **source_links(before)}, 'Start bounded scientific iteration'))
        if decision.action in (s.PlannerAction.RUN_FOLLOWUP, s.PlannerAction.DESIGN_EXPERIMENT) and before.analyses:
            records.append(event('FOLLOWUP_REQUESTED', {'round_id': round_id, 'reason': decision.reason,
                **source_links(before)}, 'New design commitment must obtain fresh exact-version approval'))
        def check():
            fresh = load_snapshot(self.ledger, decision.project_id)
            if fresh != before or not self.validator.validate(decision, fresh).valid:
                raise IllegalDecisionError('Adaptive dispatch state changed before lock')
        self.ledger.add_many(records, check=check)
        try:
            action = decision.action
            if action in (s.PlannerAction.ACCEPT_HYPOTHESIS, s.PlannerAction.REJECT_HYPOTHESIS):
                from .state_machine import selected_hypothesis
                h = selected_hypothesis(before)
                if not h: raise IllegalDecisionError('No exact hypothesis target')
                kind = 'HYPOTHESIS_ACCEPTED_FOR_CHARTER' if action == s.PlannerAction.ACCEPT_HYPOTHESIS else 'HYPOTHESIS_REJECTED'
                # Decisions overlay status through events; scientific versions/reviews remain intact.
                self.ledger.add_event(event(kind, {'hypothesis_id': h.hypothesis_id, 'version': h.version,
                    'reason': decision.reason, 'semantics': 'Sufficient for charter decision; never scientific proof',
                    **source_links(before)}, 'Hypothesis disposition with retained uncertainty and evidence basis'))
                result = {'status': kind}
            elif action == s.PlannerAction.STOP:
                result = {'status': 'COMPLETED', 'reason': decision.reason}
            elif action in (s.PlannerAction.RUN_FOLLOWUP, s.PlannerAction.DESIGN_EXPERIMENT):
                result = await self.execute_experiment_design(route, services.get('design'))
            elif action in (s.PlannerAction.GATHER_EVIDENCE, s.PlannerAction.COLLECT_MORE_DATA) and decision.target_agent == 'evidence':
                result = await self.execute_evidence(route, services.get('evidence'))
            elif action == s.PlannerAction.GENERATE_HYPOTHESES:
                result = await self.execute_hypotheses(route, services.get('hypothesis'))
            elif action == s.PlannerAction.REFINE_HYPOTHESIS:
                from autolab.hypotheses.service import HypothesisPipeline
                pipeline = services.get('hypothesis') or HypothesisPipeline(self.ledger)
                if pipeline.ledger is not self.ledger: raise IllegalDecisionError('Hypothesis ledger mismatch')
                result = await pipeline.refine(decision.project_id, critique_only=decision.target_agent == 'critic')
            elif action == s.PlannerAction.SELECT_EXPERIMENT:
                result = {'status': 'AWAITING_HUMAN_APPROVAL'}
            elif action == s.PlannerAction.REQUEST_HUMAN_APPROVAL:
                result = {'status': 'AWAITING_HUMAN_APPROVAL'}
            elif action == s.PlannerAction.PREPARE_RESOURCES:
                result = await self.execute_preparation(route, services.get('preparation'), services.get('readiness'))
            elif action == s.PlannerAction.IMPLEMENT_EXPERIMENT:
                result = await self.execute_implementation(route, services.get('implementation'))
            elif action == s.PlannerAction.RUN_EXPERIMENT:
                if 'runtime' not in services: raise IllegalDecisionError('Exact approved runtime adapter must be supplied')
                result = await self.execute_runtime(route, services['runtime'])
            elif action == s.PlannerAction.ANALYZE_RESULT:
                result = await self.execute_analysis(route, services.get('analysis'))
            else:
                raise IllegalDecisionError('No registered dispatch for this action/target')
        except Exception:
            self.ledger.add_event(event('ADAPTIVE_SPECIALIST_FAILED', {'round_id': round_id},
                'Failure retained; no blind repeat or inferred success; reconcile partial records before further work'))
            raise
        self.ledger.add_event(event('ADAPTIVE_CONTROL_RETURNED', {'round_id': round_id, 'action': decision.action.value},
            'Specialist boundary returned Planner control'))
        if decision.action in (s.PlannerAction.GATHER_EVIDENCE, s.PlannerAction.GENERATE_HYPOTHESES, s.PlannerAction.REFINE_HYPOTHESIS):
            self.ledger.add_event(event('RESEARCH_ROUND_COMPLETED', {'round_id': round_id,
                'work_decision': decision.decision_id}, 'Evidence/hypothesis work completed; next decision belongs to Planner'))
        return result

    async def continue_research(self, project_id: str, *, max_steps=4, services=None):
        """Bounded PI→specialist control. Human input is an immediate boundary."""
        from .models import ControlStage as C
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 20:
            raise ValueError('max_steps must be an integer from 1 to 20')
        routes = []
        for _ in range(max_steps):
            snapshot = load_snapshot(self.ledger, project_id)
            state = derive_control_state(snapshot)
            if state in (C.AWAITING_HUMAN_APPROVAL, C.PAUSED, C.COMPLETED, C.RUNNING, C.BLOCKED):
                return {'status': state.value, 'decisions': routes}
            # Resume only a persisted, undispatched decision. An interrupted
            # once-only dispatch stays visible and cannot trigger an automatic retry.
            pending = snapshot.decisions[-1] if snapshot.decisions else None
            dispatched = pending and any(e.event_type == 'ADAPTIVE_DISPATCHED' and e.payload.get('decision_id') == pending.decision_id for e in snapshot.events)
            returned = pending and any(e.event_type == 'ADAPTIVE_CONTROL_RETURNED' and e.payload.get('decision_id') == pending.decision_id for e in snapshot.events)
            if dispatched and not returned:
                return {'status': 'RECONCILIATION_REQUIRED', 'decisions': routes}
            if pending and not dispatched and self.validator.validate(pending, snapshot).valid:
                route = RoutingDecision(decision_id=pending.decision_id, action=pending.action,
                    target_role=pending.target_agent, reason=pending.reason,
                    context_requirements=pending.required_context_ids, control_state=state)
            else:
                route = await self.decide(project_id, max_repairs=0)
            routes.append(route.decision_id)
            if route.action in (s.PlannerAction.REQUEST_HUMAN_APPROVAL, s.PlannerAction.SELECT_EXPERIMENT):
                return {'status': 'AWAITING_HUMAN_APPROVAL', 'decisions': routes}
            await self.execute_adaptive(route, services=services)
            if route.action in (s.PlannerAction.STOP, s.PlannerAction.ACCEPT_HYPOTHESIS, s.PlannerAction.REJECT_HYPOTHESIS):
                return {'status': route.action.value, 'decisions': routes}
        return {'status': 'STEP_LIMIT', 'decisions': routes}
