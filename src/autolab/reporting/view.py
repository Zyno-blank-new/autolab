"""One project-scoped read model for status and the living research report."""
import hashlib
import json
import os

from autolab import schemas as s
from autolab.analysis.persistence import reviewed_analysis
from autolab.feasibility.persistence import current_assessment, current_packet, HUMAN_ACTORS, HUMAN_EVENTS
from autolab.orchestration.adaptive import research_history, round_history, round_count, limits, telemetry, hypothesis_disposition
from autolab.orchestration.budget import calculate_budget, calculate_time
from autolab.orchestration.models import ControlStage as C
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import (derive_control_state, selected_hypothesis,
    selected_experiment, current_run, current_analysis, latest_review)
from .public import public


def snapshot_fingerprint(snapshot):
    data = snapshot.model_dump(mode='json')
    data['events'] = [e for e in data['events'] if e['event_type'] != 'REPORT_GENERATED']
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def dump(record, *, exclude=None):
    return record.model_dump(mode='json', exclude=exclude or set()) if record else None


def review_view(review):
    return dump(review, exclude={'metadata'})


def build_view(ledger, project_id, *, now=None):
    return view_snapshot(load_snapshot(ledger, project_id), now=now)


def view_snapshot(snapshot, *, now=None):
    """No directory discovery, network, model calls or scientific interpretation."""
    state = derive_control_state(snapshot)
    hypothesis, experiment = selected_hypothesis(snapshot), selected_experiment(snapshot)
    run, analysis = current_run(snapshot), current_analysis(snapshot)
    packet, assessment = current_packet(snapshot), current_assessment(snapshot)
    budget, time = calculate_budget(snapshot), calculate_time(snapshot, now)
    blockers = []
    if state == C.PAUSED:
        blockers.append('Project is paused; resume before continuing.')
    if state == C.AWAITING_HUMAN_APPROVAL:
        blockers.append('Explicit human approval required for the current exact contract and action scope.')
    if assessment:
        blockers += assessment.blockers + assessment.user_input_required
        blockers += [f'{c.capability_id}: {c.status.value}' for c in assessment.capabilities
                     if c.status.value != 'AVAILABLE']
    readiness = next((r for r in reversed(snapshot.readiness) if experiment and
        (r.experiment_id, r.experiment_version) == (experiment.experiment_id, experiment.version)), None)
    if readiness and readiness.verdict != s.ReadinessVerdict.PASS:
        blockers += [f'{readiness.readiness_id}: {readiness.verdict.value}', *readiness.failed_checks]
    for model, row, id_field, review_type in ((s.Hypothesis, hypothesis, 'hypothesis_id', 'hypothesis'),
        (s.ExperimentSpec, experiment, 'experiment_id', 'experiment')):
        review = latest_review(snapshot, model, getattr(row, id_field), row.version, review_type) if row else None
        if review and review.verdict != s.ReviewVerdict.PASS:
            blockers += [f'{review.review_id}: {review.verdict.value} for {getattr(row, id_field)} v{row.version}',
                *[str(issue.get('finding', issue.get('detail', issue))) for issue in review.issues]]
    for event in snapshot.events:
        if event.event_type in ('PROJECT_BLOCKED', 'IMPLEMENTATION_BLOCKED', 'RESOURCE_PREPARATION_BLOCKED'):
            blockers.append(f'{event.event_id} (historical blocker): {event.summary}')
    next_decision = snapshot.decisions[-1] if snapshot.decisions else None
    stopped = any(d.action == s.PlannerAction.STOP for d in snapshot.decisions) or any(
        e.event_type == 'HUMAN_STOPPED' and e.actor in HUMAN_ACTORS for e in snapshot.events) or snapshot.charter.status == s.ProjectStatus.STOPPED
    scope = snapshot.authorized_scope or snapshot.charter
    hypothesis_rows = []
    for h in snapshot.hypotheses:
        hypothesis_rows.append({**dump(h), 'disposition': hypothesis_disposition(snapshot, h),
            'review': review_view(latest_review(snapshot, s.Hypothesis, h.hypothesis_id, h.version, 'hypothesis'))})
    experiment_rows = []
    for e in snapshot.experiments:
        selection = next((x for x in reversed(snapshot.events) if x.event_type == 'EXPERIMENT_SELECTED'
            and x.payload.get('experiment_id', x.target_id) == e.experiment_id
            and x.payload.get('version', 1) == e.version), None)
        rr = [r for r in snapshot.runs if (r.experiment_id, r.experiment_version) == (e.experiment_id, e.version)]
        readiness_rows = [r for r in snapshot.readiness if (r.experiment_id, r.experiment_version) == (e.experiment_id, e.version)]
        review = latest_review(snapshot, s.ExperimentSpec, e.experiment_id, e.version, 'experiment')
        blocked = bool((readiness_rows and readiness_rows[-1].verdict == s.ReadinessVerdict.BLOCK) or
            (review and review.verdict in (s.ReviewVerdict.BLOCK, s.ReviewVerdict.REJECT)) or
            any(x.event_type in ('RESOURCE_PREPARATION_BLOCKED', 'IMPLEMENTATION_BLOCKED', 'PROJECT_BLOCKED')
                and x.target_id == e.experiment_id for x in snapshot.events) or
            (assessment and assessment.experiment_id == e.experiment_id and
             assessment.experiment_version == e.version and assessment.status == 'BLOCKED'))
        execution = 'EXECUTED' if any(r.status == s.RunStatus.COMPLETED for r in rr) else (
            'ATTEMPTED / NO COMPLETED RUN' if any(r.status != s.RunStatus.PENDING for r in rr) else
            'PENDING / NOT EXECUTED' if rr else 'BLOCKED / NOT EXECUTED' if blocked else 'NOT EXECUTED')
        experiment_rows.append({**dump(e), 'execution': execution,
            'selection': {k: selection.payload.get(k) for k in ('reason', 'round_id', 'parent_experiment_id',
                'parent_experiment_version', 'parent_run_id', 'parent_analysis_id', 'parent_analysis_version',
                'decision_id', 'selection_decision_id', 'followup_reason')} if selection else None,
            'review': review_view(review)})
    run_rows = []
    for r in snapshot.runs:
        run_rows.append({**dump(r, exclude={'environment_metadata', 'input_manifest', 'output_manifest'}),
            'duration_seconds': r.environment_metadata.get('duration_seconds'),
            'environment': {k: r.environment_metadata.get(k) for k in ('python_version', 'framework_version',
                'framework_source_sha256', 'exit_status', 'metric_exit_status', 'isolation', 'provider_inference')
                if r.environment_metadata.get(k) is not None},
            'usage': r.environment_metadata.get('usage', r.output_manifest.get('usage')),
            'artifacts': r.output_manifest.get('artifacts', {}),
            'metrics': [dump(m) for m in snapshot.metrics if m.run_id == r.run_id]})
    analysis_rows = [{**dump(a, exclude={'evidence_pins', 'confidence'}),
        'review': review_view(latest_review(snapshot, s.ScientificAnalysis, a.analysis_id, a.version, 'analysis')),
        'current_reviewed': reviewed_analysis(snapshot, a)} for a in snapshot.analyses]
    # Deliberately do not export arbitrary agent/debug payloads or source code.
    decisions = [dump(d) for d in snapshot.decisions]
    human = [{**dump(e, exclude={'payload'}), 'scope': {k: e.payload.get(k) for k in (
        'experiment_id', 'experiment_version', 'packet_id', 'assessment_id', 'approved_actions',
        'implementation_id', 'max_cost_usd', 'max_runtime_minutes', 'note', 'reason')}}
        for e in snapshot.events if e.actor in HUMAN_ACTORS and e.event_type in HUMAN_EVENTS | {
            'HUMAN_STOPPED', 'PROJECT_PAUSED', 'PROJECT_RESUMED'}]
    local_inspections = [{**dump(e, exclude={'payload'}), 'inspection': {k: e.payload.get(k) for k in (
        'run_id', 'analysis_id', 'analysis_version', 'raw_sha256', 'condition_sample_ids',
        'matched_identity_and_order', 'unique_ids_per_condition', 'scope', 'observations')}}
        for e in snapshot.events if e.event_type == 'LOCAL_RESULT_EVIDENCE_INSPECTED']
    milestones = [{**dump(e, exclude={'payload'}),
        'decision_id': e.payload.get('selection_decision_id', e.payload.get('decision_id')),
        'action': e.payload.get('action'), 'round_id': e.payload.get('round_id')}
        for e in snapshot.events if e.event_type in {
        'PROJECT_CREATED', 'EVIDENCE_ADDED', 'HYPOTHESIS_CREATED', 'HYPOTHESIS_REFINED', 'EXPERIMENT_SELECTED',
        'HUMAN_APPROVED', 'HUMAN_REJECTED', 'HUMAN_MODIFICATION_REQUESTED', 'PROJECT_PAUSED', 'PROJECT_RESUMED',
        'HUMAN_STOPPED', 'EXPERIMENT_RUN_COMPLETED', 'EXPERIMENT_RUN_FAILED', 'SCIENTIFIC_ANALYSIS_CREATED',
        'SCIENTIFIC_ANALYSIS_REVISED', 'PLANNER_DECISION', 'RESEARCH_STOPPED', 'ADAPTIVE_CONTROL_RETURNED',
        'ADAPTIVE_SPECIALIST_FAILED', 'LOCAL_RESULT_EVIDENCE_INSPECTED', 'HYPOTHESIS_REJECTED',
        'HYPOTHESIS_ACCEPTED_FOR_CHARTER', 'ROUND_LIMIT_REACHED'}]
    limitations = list(dict.fromkeys([x for a in snapshot.analyses for x in
        [*a.limitations, *a.remaining_uncertainties]] + [x for e in snapshot.experiments for x in
        e.potential_confounders] + blockers))
    if budget.unknown_actual_cost_ids:
        limitations.append('Actual cost UNKNOWN: ' + ', '.join(budget.unknown_actual_cost_ids))
    result = {'schema': 'autolab.project-view.v1', 'project_id': snapshot.charter.project_id,
        'ledger_fingerprint': snapshot_fingerprint(snapshot), 'charter': dump(snapshot.charter),
        'authorized_scope': dump(snapshot.authorized_scope), 'state': state.value,
        'paused': state == C.PAUSED, 'stopped': stopped, 'terminal': state == C.COMPLETED,
        'current': {'hypothesis': dump(hypothesis), 'experiment': dump(experiment), 'run': dump(run, exclude={
            'environment_metadata', 'input_manifest', 'output_manifest'}), 'analysis': dump(analysis, exclude={
            'evidence_pins', 'confidence'}), 'analysis_reviewed_current': reviewed_analysis(snapshot, analysis)},
        'latest_decision': dump(next_decision), 'human_action_required': state == C.AWAITING_HUMAN_APPROVAL,
        'approval_packet_id': packet.packet_id if packet else None, 'blockers': list(dict.fromkeys(blockers)),
        'budget': dump(budget), 'time': dump(time), 'round_count': round_count(snapshot), 'limits': limits(snapshot),
        'openai_access': 'configured' if os.environ.get('OPENAI_API_KEY') else 'required',
        'sources': [dump(x, exclude={'metadata', 'abstract'}) | {'identifiers': {k: x.metadata.get(k)
            for k in ('arxiv_id', 'openalex_id', 'provider_id', 'pdf_url') if x.metadata.get(k)}} for x in snapshot.sources],
        'evidence': [dump(x) for x in snapshot.evidence], 'hypotheses': hypothesis_rows,
        'candidates': [dump(x) for x in snapshot.candidates], 'experiments': experiment_rows,
        'resources': [dump(x, exclude={'metadata'}) | {'provenance': {k: x.metadata.get(k)
            for k in ('source_uri', 'license', 'parent_ids', 'previous_resource_id', 'acquisition_mode',
                'creation_tool', 'seed', 'specification') if x.metadata.get(k) is not None}} for x in snapshot.resources],
        'readiness': [dump(x, exclude={'metadata'}) for x in snapshot.readiness],
        'implementations': [dump(x, exclude={'metadata'}) | {'test_status': next((
            {'event_id': e.event_id, 'status': e.payload.get('status'),
             'static_pass': e.payload.get('checks', {}).get('static_pass'),
             'tests_pass': e.payload.get('checks', {}).get('tests_pass'),
             'framework_check_count': e.payload.get('checks', {}).get('test_count'),
             'generated_test_count': e.payload.get('checks', {}).get('generated_count'),
             'checks_fingerprint': e.payload.get('checks_fingerprint')}
            for e in reversed(snapshot.events) if e.event_type == 'IMPLEMENTATION_TESTED'
            and e.target_id == x.implementation_id and e.actor == 'implementation_validator'), None),
            'review': review_view(latest_review(snapshot, s.ImplementationRecord, x.implementation_id, 1, 'code'))}
            for x in snapshot.implementations], 'runs': run_rows, 'analyses': analysis_rows, 'decisions': decisions,
        'human_decisions': human, 'rounds': round_history(snapshot, max(1, len(snapshot.events))),
        'research_history': research_history(snapshot, max(1, len(snapshot.runs))), 'telemetry': telemetry(snapshot),
        'milestones': milestones, 'local_inspections': local_inspections, 'limitations': limitations,
        'costs': [dump(x, exclude={'metadata'}) for x in snapshot.costs],
        'scope': {'effective_objective': scope.objective, 'effective_project_id': scope.project_id}}
    return public(result)


def render_status(view):
    current = view['current']
    def identity(row, key):
        return f"{row[key]} v{row['version']}" if row and 'version' in row else row[key] if row else 'none'
    decision = view['latest_decision']
    result = current['run']
    analysis = current['analysis']
    b, t = view['budget'], view['time']
    rows = [f"PROJECT {view['project_id']}", f"Question: {view['charter']['research_question']}",
        f"Objective: {view['scope']['effective_objective']}", f"STATE {view['state']} | paused={view['paused']} | stopped={view['stopped']}",
        f"Hypothesis: {identity(current['hypothesis'], 'hypothesis_id')}",
        f"Experiment: {identity(current['experiment'], 'experiment_id')}",
        f"LATEST RESULT {result['run_id'] + ': ' + result['status'] if result else 'Execution is in progress; no finalized result.' if view['state'] == 'RUNNING' else 'No finalized experiment result yet.'}",
        f"Analysis: {identity(analysis, 'analysis_id')}" + (f" — {analysis['hypothesis_assessment']}; current reviewed={current['analysis_reviewed_current']}" if analysis else ''),
        f"NEXT DECISION {decision['decision_id'] + ': ' + decision['action'] if decision else 'Planner has not decided yet.'}",
        f"WHY {decision['reason'][:600] if decision else 'none recorded'}",
        f"HUMAN ACTION REQUIRED {'yes; review ' + (view['approval_packet_id'] or 'current approval scope') if view['human_action_required'] else 'no'}",
        f"Budget: known actual ${b['actual_spent_usd']:g}; recorded estimates ${b['estimated_spent_usd']:g}; remaining known ${b['remaining_budget_usd']:g}",
        f"Unknown actual costs: {', '.join(b['unknown_actual_cost_ids']) or 'none recorded; unrecorded costs are not measured'}",
        f"Remaining time: {str(round(t['remaining_minutes'], 2)) + ' minutes' if t['remaining_minutes'] is not None else 'no configured limit'}",
        f"Rounds: {view['round_count']} / {view['limits'].get('max_rounds', 'no configured limit')}",
        'BLOCKERS ' + ('; '.join(x[:200] for x in view['blockers'][:6]) or 'none recorded'),
        f"OpenAI credential: {view['openai_access']}"]
    if result:
        record = next((r for r in view['runs'] if r['run_id'] == result['run_id']), None)
        rows[7:7] = [f"  {m['metric_id']}: {m['metadata'].get('condition', 'unspecified')} {m['metric_name']}={m['metric_value']}"
                     for m in record['metrics']] if record else []
    if analysis:
        row = next((a for a in view['analyses'] if a['analysis_id'] == analysis['analysis_id']
                    and a['version'] == analysis['version']), None)
        review = row.get('review') if row else None
        rows.append('LATEST REVIEWED ANALYSIS ' + identity(analysis, 'analysis_id') +
            f"; assessment={analysis['hypothesis_assessment']}; Critic=" +
            (f"{review['review_id']} {review['verdict']}" if review else 'not reviewed') +
            f"; current eligibility={current['analysis_reviewed_current']}")
    return '\n'.join(rows)
