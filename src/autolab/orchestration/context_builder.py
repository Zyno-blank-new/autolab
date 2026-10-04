"""Bounded structured context; papers, logs, and full event payloads stay out."""
import logging
from datetime import datetime
from autolab import schemas as s
from .budget import calculate_budget, calculate_time
from .decision_validator import DecisionValidator
from .models import ContextLimits, PlannerContext, ProjectSnapshot
from .state_machine import (charter_fingerprint, current_analysis, current_implementation, current_readiness,
                            current_run, derive_control_state, latest_versions, selected_experiment, selected_hypothesis)

log = logging.getLogger(__name__)


class ContextTooLargeError(RuntimeError):
    pass


class ContextBuilder:
    def __init__(self, limits: ContextLimits | None = None, validator: DecisionValidator | None = None):
        self.limits = limits or ContextLimits()
        self.validator = validator or DecisionValidator()

    def build(self, snapshot: ProjectSnapshot, *, now: datetime | None = None) -> PlannerContext:
        limits = self.limits
        cut = lambda text: text[:limits.summary_chars]
        summaries = {}
        omitted = {}
        # Reuse role-specific compact summaries, retaining exact review versions.
        from autolab.hypotheses.context import hypothesis_summary
        from autolab.experiment_design.context import candidate_history_summary
        from .state_machine import latest_review
        def summarize_hypothesis(h):
            review = latest_review(snapshot, s.Hypothesis, h.hypothesis_id, h.version)
            if review is None and h.status == s.HypothesisStatus.REJECTED:
                review = next((r for r in reversed(snapshot.reviews) if r.target_id == h.hypothesis_id
                               and r.target_type in ("Hypothesis", "hypotheses")), None)
            row = hypothesis_summary(h, review, chars=limits.summary_chars)
            if review:
                row["critic"]["concerns"] = [{"problem": cut(str(issue.get("problem", ""))),
                                              "resolution": cut(str(issue.get("resolution", "")))} for issue in review.issues[:2]]
            return row
        def summarize_candidate(c):
            return candidate_history_summary(snapshot, c, chars=limits.summary_chars)
        groups = {
            "evidence": [(e.evidence_id, {"id": e.evidence_id, "source_id": e.source_id, "claim": cut(e.claim), "confidence": e.confidence, "tags": e.tags[:10]}) for e in snapshot.evidence],
            "hypotheses": [(h.hypothesis_id, summarize_hypothesis(h)) for h in latest_versions(snapshot.hypotheses, "hypothesis_id")],
            "candidates": [(c.candidate_id, summarize_candidate(c)) for c in latest_versions(snapshot.candidates, "candidate_id")],
            "experiments": [(e.experiment_id, {"id": e.experiment_id, "version": e.version, "title": cut(e.title), "status": e.status.value}) for e in latest_versions(snapshot.experiments, "experiment_id")],
            "reviews": [(r.review_id, {"id": r.review_id, "target_id": r.target_id, "target_version": r.target_version, "review_type": cut(r.review_type), "verdict": r.verdict.value,
                                        "recommendations": [cut(x) for x in r.recommendations[:2]]}) for r in snapshot.reviews],
            "decisions": [(d.decision_id, {"id": d.decision_id, "action": d.action.value, "target_agent": d.target_agent, "reason": cut(d.reason)}) for d in snapshot.decisions],
            "events": [(e.event_id, {"id": e.event_id, "event_type": cut(e.event_type), "target_id": e.target_id, "summary": cut(e.summary)}) for e in snapshot.events],
        }
        for name, rows in groups.items():
            limit = {"decisions": limits.recent_decisions, "events": limits.recent_events}.get(name, limits.records_per_kind)
            summaries[name] = [summary for _, summary in rows[-limit:]]
            omitted[name] = max(0, len(rows)-limit)
        summaries["rejected_hypotheses"] = [{"id": h.hypothesis_id, "status": h.status.value, "statement": cut(h.statement)}
            for h in latest_versions(snapshot.hypotheses, "hypothesis_id") if h.status == s.HypothesisStatus.REJECTED][-limits.records_per_kind:]
        if snapshot.analyses:
            for row in summaries['reviews']:
                row['recommendations'] = [x[:180] for x in row['recommendations'][:1]]
        current = {}
        hypothesis = selected_hypothesis(snapshot)
        experiment = selected_experiment(snapshot)
        readiness = current_readiness(snapshot)
        implementation = current_implementation(snapshot)
        run = current_run(snapshot)
        analysis = current_analysis(snapshot)
        if hypothesis:
            current["hypothesis"] = summarize_hypothesis(hypothesis)
            from .adaptive import hypothesis_disposition
            current['hypothesis']['charter_disposition'] = hypothesis_disposition(snapshot, hypothesis)
        if experiment:
            current["experiment"] = {"id": experiment.experiment_id, "version": experiment.version, "hypothesis_id": experiment.hypothesis_id,
                "objective": cut(experiment.objective), "primary_metric": cut(experiment.primary_metric), "status": experiment.status.value,
                "estimated_cost_usd": experiment.estimated_cost_usd, "estimated_runtime_minutes": experiment.estimated_runtime_minutes}
            from autolab.feasibility.persistence import current_assessment, human_event
            assessment = current_assessment(snapshot, experiment)
            if assessment:
                current["feasibility"] = {"id": assessment.assessment_id, "version": assessment.version,
                    "experiment_id": assessment.experiment_id, "experiment_version": assessment.experiment_version,
                    "status": assessment.status.value, "cost_range_usd": assessment.cost.estimate_usd.model_dump(),
                    "budget_status": assessment.budget_status.value,
                    "runtime_range_minutes": assessment.runtime_minutes.model_dump(), "time_status": assessment.time_status.value,
                    "blockers": [cut(x) for x in assessment.blockers[:3]], "warnings": [cut(x) for x in assessment.warnings[:2]],
                    "user_input_required": [cut(x) for x in assessment.user_input_required[:3]],
                    "unknown_cost_drivers": [cut(x) for x in assessment.cost.unknown_cost_drivers[:2]]}
            response = human_event(snapshot, experiment)
            if response:
                from .state_machine import approval_for
                scope = approval_for(snapshot, s.PlannerAction.PREPARE_RESOURCES)
                current["human_approval"] = {"event_id": response.event_id, "actor": response.actor,
                    "decision": {"HUMAN_APPROVED": "APPROVE", "HUMAN_REJECTED": "REJECT"}.get(response.event_type, "MODIFY"),
                    "experiment_id": experiment.experiment_id, "experiment_version": experiment.version,
                    "assessment_id": response.payload.get("assessment_id"), "scope_current": scope is not None,
                    "max_cost_usd": scope.max_cost_usd if scope else None,
                    "max_runtime_minutes": scope.max_runtime_minutes if scope else None,
                    "approved_actions": [a.value for a in scope.approved_actions] if scope else [],
                    "note": cut(response.payload.get("note") or "")}
        from autolab.preparation.manifest import current_manifest, current_plan
        from .state_machine import readiness_passes
        plan, manifest = current_plan(snapshot), current_manifest(snapshot)
        if plan:
            current["preparation"] = {"plan_id": plan.plan_id, "plan_version": plan.version,
                "repair_count": plan.version - 1, "blockers": [cut(x) for x in plan.blockers[:3]],
                "user_input_required": [cut(x) for x in plan.user_input_required[:3]],
                "material_changes": [cut(x) for x in plan.material_changes[:3]]}
        if manifest:
            current["resource_manifest"] = {"id": manifest.manifest_id, "plan_id": manifest.plan_id,
                "experiment_id": manifest.experiment_id, "experiment_version": manifest.experiment_version,
                "resources": [{"id": p.resource_id, "version": p.version, "status": p.status,
                    "type": next((r.resource_type for r in snapshot.resources if r.resource_id == p.resource_id), "MISSING")} for p in manifest.resources],
                "warnings": [cut(w) for w in manifest.unresolved_warnings[:3]]}
        if readiness:
            current["readiness"] = {"id": readiness.readiness_id, "verdict": readiness.verdict.value, "failed_checks": [cut(x) for x in readiness.failed_checks[:3]],
                "current_pass": readiness_passes(snapshot), "repair_count": readiness.metadata.get("repair_count", 0),
                "warnings": [cut(x) for x in readiness.warnings[:2]]}
        if implementation:
            from .state_machine import implementation_passes
            review = latest_review(snapshot, s.ImplementationRecord, implementation.implementation_id, review_type="code")
            from autolab.implementation.persistence import current_checks
            checked = current_checks(snapshot, implementation)
            checks = checked.model_dump(mode='json') if checked else {}
            current["implementation"] = {"id": implementation.implementation_id, "code_version": cut(implementation.code_version),
                "status": "READY" if implementation_passes(snapshot) else cut(implementation.status),
                "experiment_version": implementation.experiment_version, "revision": implementation.metadata.get('revision'),
                "code_review": review.verdict.value if review else None,
                "tests_pass": checks.get('tests_pass', False), "static_pass": checks.get('static_pass', False),
                "current_audit_pass": implementation_passes(snapshot),
                "warnings": [cut(w) for w in implementation.metadata.get('plan', {}).get('limitations', [])[:2]],
                "blockers": [cut(str(i.get('problem', ''))) for i in (review.issues if review else [])[:3]]}
        if run:
            from autolab.runtime.persistence import valid_result
            current["run"] = {"id": run.run_id, "status": run.status.value, "experiment_id": run.experiment_id,
                "experiment_version":run.experiment_version,"duration_seconds":run.environment_metadata.get('duration_seconds'),
                "sample_observations":run.output_manifest.get('observation_count'),"integrity_valid":valid_result(snapshot,run),
                "usage":run.environment_metadata.get('usage',{}),"actual_cost_usd":run.cost_usd,
                "actual_cost_status":run.environment_metadata.get('actual_cost_status','UNKNOWN'),
                "artifacts":[{'name':name,'path':pin.get('path'),'sha256':pin.get('sha256')} for name,pin in list(run.output_manifest.get('artifacts',{}).items())[:3]],
                "error":cut(run.error_message or '')}
            current["metrics"] = [{"id": m.metric_id, "name": cut(m.metric_name), "value": m.metric_value, "unit": m.unit,
                                    "condition":m.metadata.get('condition'),"role":m.metadata.get('role'),"denominator":m.metadata.get('denominator')}
                                  for m in snapshot.metrics if m.run_id == run.run_id][-limits.records_per_kind:]
        scope_event = next((e for e in reversed(snapshot.events) if e.event_type=='RESULT_INTERPRETATION_AUTHORIZED' and e.actor=='test_human'), None)
        if scope_event:
            scope = scope_event.payload.get('analysis_charter', {})
            current['analysis_scope'] = {'linked_project_id':scope.get('project_id'),
                'objective':cut(scope.get('objective','')),'scope':cut(scope.get('constraints',{}).get('scope','')),
                'source_run_ids':scope_event.payload.get('source_run_ids',[])}
        if analysis:
            from autolab.analysis.persistence import analysis_current, reviewed_analysis
            review = latest_review(snapshot, s.ScientificAnalysis, analysis.analysis_id, analysis.version, 'analysis')
            current["analysis"] = {"id": analysis.analysis_id, "version":analysis.version,
                "hypothesis_id":analysis.hypothesis_id,"hypothesis_version":analysis.hypothesis_version,
                "experiment_id":analysis.experiment_id,"experiment_version":analysis.experiment_version,"run_id":analysis.run_id,
                "metric_ids":analysis.metric_ids,"assessment": analysis.hypothesis_assessment.value,
                "critic_verdict":review.verdict.value if review else None,
                "fresh":analysis_current(snapshot,analysis),"reviewed_current":reviewed_analysis(snapshot,analysis),
                "findings":[cut(x) for x in analysis.key_findings[:3]],
                "criteria":analysis.criteria_evaluation,
                "interpretation": cut(analysis.interpretation), "limitations": [cut(x) for x in analysis.limitations[:3]],
                "unresolved_confounders":[c for c in analysis.confounders if c.get('status')!='CONTROLLED'][:3]}
        from .adaptive import research_history, result_packet, round_count, limits as adaptive_limits
        summaries['research_history'] = research_history(snapshot, limits.records_per_kind)
        from .adaptive import round_history
        summaries['research_rounds'] = [{k: row.get(k) for k in ('round_id', 'parent_round', 'trigger_decision',
            'started_at', 'ended_at', 'experiment_ids', 'evidence_ids', 'hypotheses', 'decisions')}
            for row in round_history(snapshot, limits.records_per_kind)]
        current['reviewed_result'] = result_packet(snapshot)
        if current['reviewed_result']:
            current['reviewed_result']['limitations'] = [cut(x) for x in current['reviewed_result']['limitations'][:4]]
            current['reviewed_result']['findings'] = [cut(x) for x in current['reviewed_result']['findings'][:3]]
            request = current['reviewed_result'].get('planner_request')
            if request: request['reason'] = cut(request['reason'])
            compact_confounders = lambda rows: [{k: cut(v) if isinstance(v, str) else v for k, v in row.items()}
                                               for row in rows[:3]]
            current['reviewed_result']['unresolved_confounders'] = compact_confounders(current['reviewed_result']['unresolved_confounders'])
            if 'analysis' in current:
                current['analysis']['unresolved_confounders'] = compact_confounders(current['analysis']['unresolved_confounders'])
            # Shared fields already exist in current.analysis. Keep a small role
            # packet here rather than duplicating full original prose/criteria.
            current['reviewed_result']['limitations'] = [x[:180] for x in current['reviewed_result']['limitations'][:3]]
            current['reviewed_result']['findings'] = [x[:180] for x in current['reviewed_result']['findings'][:2]]
            if run:
                from pathlib import Path
                for artifact in current['run']['artifacts']:
                    if artifact.get('path'): artifact['path'] = Path(artifact['path']).name
        inspection = next((e for e in reversed(snapshot.events) if e.event_type == 'LOCAL_RESULT_EVIDENCE_INSPECTED'
                           and run and e.payload.get('run_id') == run.run_id), None)
        if inspection and current['reviewed_result']:
            current['existing_result_inspection'] = {k: inspection.payload[k] for k in
                ('run_id', 'raw_sha256', 'condition_sample_ids', 'matched_identity_and_order', 'unique_ids_per_condition', 'scope')}
            current['existing_result_inspection']['observed_pairs'] = [
                {'sample_id': sample_id, 'conditions': {o['condition']: o['outputs'] for o in inspection.payload['observations'] if o['sample_id'] == sample_id}}
                for sample_id in next(iter(inspection.payload['condition_sample_ids'].values()))[:6]]
        current['adaptive_limits'] = {'rounds_started': round_count(snapshot), **adaptive_limits(snapshot)}
        if snapshot.authorized_scope:
            current['authorized_research_scope'] = snapshot.authorized_scope.model_dump(mode='json')
        if experiment:
            selection = next((e for e in reversed(snapshot.events) if e.event_type == 'EXPERIMENT_SELECTED'
                              and e.target_id == experiment.experiment_id), None)
            current['experiment']['selection_reason'] = cut(selection.payload.get('reason', '')) if selection else None
        context = PlannerContext(charter=snapshot.charter, control_state=derive_control_state(snapshot),
            project_status=snapshot.charter.status, budget=calculate_budget(snapshot), time=calculate_time(snapshot, now),
            counts={name: len(getattr(snapshot, name)) for name in ("sources", "evidence", "hypotheses", "experiments", "runs")},
            summaries=summaries, current_records=current,
            available_roles=list(self.validator.roles.roles), available_actions=self.validator.legal_actions(snapshot, now=now),
            action_targets={action.value: list(targets) for action, targets in self.validator.roles.action_targets.items()},
            omitted_records=omitted, charter_fingerprint=charter_fingerprint(snapshot.authorized_scope or snapshot.charter))
        if len(context.model_dump_json()) > limits.max_json_chars:
            raise ContextTooLargeError("Planner context exceeds the configured JSON limit; reduce limits or charter size.")
        log.info("PLANNER_CONTEXT_BUILT project=%s state=%s", snapshot.charter.project_id, context.control_state)
        return context
