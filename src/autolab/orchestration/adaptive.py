"""Event-backed iterations, exact decision receipts and canonical research history.

This is deterministic control software, not a scientific decision policy.
"""
import hashlib
import json
import re
from autolab import schemas as s
from .budget import calculate_budget, calculate_time
from .state_machine import current_analysis, current_run, selected_experiment, selected_hypothesis, latest_review

A = s.PlannerAction
NEW_WORK = {A.GATHER_EVIDENCE, A.COLLECT_MORE_DATA, A.GENERATE_HYPOTHESES,
            A.REFINE_HYPOTHESIS, A.RUN_FOLLOWUP, A.DESIGN_EXPERIMENT}


def state_pin(snapshot):
    """Exclude audit events and decisions; include every scientific version/cost."""
    data = snapshot.model_dump(mode='json', exclude={'events', 'decisions'})
    # Selection/lifecycle is scientific control state, unlike progress events.
    data['control_events'] = [e.model_dump(mode='json') for e in snapshot.events if e.event_type in (
        'HYPOTHESIS_SELECTED', 'EXPERIMENT_SELECTED', 'PROJECT_PAUSED', 'PROJECT_RESUMED',
        'PROJECT_BLOCKED', 'PROJECT_UNBLOCKED', 'HUMAN_APPROVED', 'HUMAN_REJECTED', 'HUMAN_MODIFY',
        'HUMAN_STOPPED', 'HUMAN_MODIFICATION_REQUESTED', 'LOCAL_RESULT_EVIDENCE_INSPECTED')]
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def decision_receipt(snapshot, decision_id):
    return next((e for e in reversed(snapshot.events) if e.event_type == 'ADAPTIVE_DECISION_CREATED'
                 and e.payload.get('decision_id') == decision_id), None)


def source_links(snapshot):
    a, r, e, h = current_analysis(snapshot), current_run(snapshot), selected_experiment(snapshot), selected_hypothesis(snapshot)
    return {'parent_experiment_id': e.experiment_id if e else None,
            'parent_experiment_version': e.version if e else None,
            'parent_run_id': r.run_id if r else None,
            'parent_analysis_id': a.analysis_id if a else None,
            'parent_analysis_version': a.version if a else None,
            'source_hypothesis_id': a.hypothesis_id if a else None,
            'source_hypothesis_version': a.hypothesis_version if a else None,
            'hypothesis_id': h.hypothesis_id if h else None,
            'hypothesis_version': h.version if h else None}


def rounds(snapshot):
    return [e for e in snapshot.events if e.event_type == 'RESEARCH_ROUND_STARTED']


def limits(snapshot):
    result = {}
    for key in ('max_rounds', 'max_experiments'):
        value = (snapshot.authorized_scope or snapshot.charter).constraints.get(key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'Charter {key} must be a positive integer')
            result[key] = value
    return result


def round_count(snapshot):
    return len(rounds(snapshot)) or (1 if snapshot.runs else 0)


def work_block(snapshot, action):
    """Hard caps stop additional work, while permitting completion/interpretation."""
    if action not in NEW_WORK:
        return None
    if not snapshot.runs and not rounds(snapshot) and not limits(snapshot):
        # Preserve pre-result Phase 3–11 reasoning semantics. Consequential
        # spending is still governed by the existing exact approval gate.
        return None
    budget, time = calculate_budget(snapshot), calculate_time(snapshot)
    if budget.remaining_budget_usd == 0:
        return 'Known project budget is exhausted'
    if time.remaining_minutes == 0:
        return 'Hard project time limit is exhausted'
    try:
        caps = limits(snapshot)
    except ValueError as error:
        return str(error)
    # A persisted trigger may finish its active round; a new PI choice starts another.
    active = rounds(snapshot)[-1] if rounds(snapshot) else None
    finished = active and any(e.event_type == 'RESEARCH_ROUND_COMPLETED' and
        e.payload.get('round_id') == active.payload['round_id'] for e in snapshot.events)
    if (not active or finished) and round_count(snapshot) >= caps.get('max_rounds', float('inf')):
        return 'Hard maximum research rounds reached'
    if action in (A.RUN_FOLLOWUP, A.DESIGN_EXPERIMENT) and len({(r.experiment_id, r.experiment_version) for r in snapshot.runs}) >= caps.get('max_experiments', float('inf')):
        return 'Hard maximum experiment count reached'
    return None


def result_packet(snapshot):
    """Current reviewed evidence only; stale history remains explicitly historical."""
    from autolab.analysis.persistence import reviewed_analysis
    a = current_analysis(snapshot)
    if not a or not reviewed_analysis(snapshot, a):
        return {}
    from autolab.analysis.result_summary import build_result_summary
    summary = build_result_summary(snapshot)
    review = latest_review(snapshot, s.ScientificAnalysis, a.analysis_id, a.version, 'analysis')
    decision = snapshot.decisions[-1] if snapshot.decisions else None
    return {**source_links(snapshot), 'assessment': a.hypothesis_assessment.value,
        'metrics': summary.metrics, 'differences': summary.differences, 'conditions': summary.conditions,
        'criteria': a.criteria_evaluation, 'findings': a.key_findings[:4],
        'limitations': [x[:600] for x in a.limitations[:6]],
        'unresolved_confounders': [x for x in a.confounders if x.get('status') != 'CONTROLLED'][:6],
        'critic': {'id': review.review_id, 'verdict': review.verdict.value, 'issues': review.issues[:4]},
        'planner_request': {'id': decision.decision_id, 'action': decision.action.value,
                            'reason': decision.reason[:1200]} if decision else None}


def research_history(snapshot, count=6):
    """No generated prose. Both favorable and unfavorable results are retained."""
    rows = []
    for run in snapshot.runs[-count:]:
        spec = next((e for e in snapshot.experiments if (e.experiment_id, e.version) ==
                     (run.experiment_id, run.experiment_version)), None)
        analysis = next((a for a in reversed(snapshot.analyses) if a.run_id == run.run_id), None)
        review = latest_review(snapshot, s.ScientificAnalysis, analysis.analysis_id, analysis.version, 'analysis') if analysis else None
        rows.append({'experiment_id': run.experiment_id, 'version': run.experiment_version,
            'hypothesis_id': spec.hypothesis_id if spec else None, 'purpose': spec.objective[:400] if spec else None,
            'run_id': run.run_id, 'status': run.status.value,
            'metrics': [{'id': m.metric_id, 'name': m.metric_name, 'value': m.metric_value,
                'condition': m.metadata.get('condition'), 'role': m.metadata.get('role')}
                for m in snapshot.metrics if m.run_id == run.run_id][:8],
            'analysis': {'id': analysis.analysis_id, 'version': analysis.version,
                'assessment': analysis.hypothesis_assessment.value, 'limitations': [x[:320] for x in analysis.limitations[:3]],
                'critic_verdict': review.verdict.value if review else None,
                'eligibility': 'historical; current eligibility evaluated separately'} if analysis else None})
        selection = next((e for e in reversed(snapshot.events) if e.event_type == 'EXPERIMENT_SELECTED'
                          and e.target_id == run.experiment_id), None)
        rows[-1]['lineage'] = {key: selection.payload.get(key) for key in ('round_id', 'parent_experiment_id',
            'parent_run_id', 'parent_analysis_id', 'decision_id', 'selection_decision_id', 'followup_reason')} if selection else {}
    return rows


def round_history(snapshot, count=6):
    entries = []
    starts = rounds(snapshot)
    for i, start in enumerate(starts):
        end = next((e for e in snapshot.events if e.event_type == 'RESEARCH_ROUND_COMPLETED'
                    and e.payload.get('round_id') == start.payload['round_id']), None)
        window = [e for e in snapshot.events if e.created_at >= start.created_at and
                  (i+1 == len(starts) or e.created_at < starts[i+1].created_at)]
        entries.append({**start.payload, 'started_at': start.payload.get('started_at', start.created_at.isoformat()),
            'ended_at': end.created_at.isoformat() if end else None,
            'result': end.payload if end else None,
            'evidence_ids': [e.target_id for e in window if e.event_type == 'EVIDENCE_ADDED'],
            'hypotheses': [e.target_id for e in window if e.event_type in ('HYPOTHESIS_CREATED', 'HYPOTHESIS_REFINED')],
            'experiment_ids': [e.target_id for e in window if e.event_type == 'EXPERIMENT_SELECTED'],
            'decisions': [e.payload.get('decision_id') for e in window if e.event_type == 'PLANNER_DECISION'],
            'local_evidence_inspections': [e.event_id for e in window if e.event_type == 'LOCAL_RESULT_EVIDENCE_INSPECTED']})
    return entries[-count:]


def normalized(value):
    if isinstance(value, str):
        return re.sub(r'\s+', ' ', value.strip().lower())
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in sorted(value.items()) if k not in (
            'planning_limitations', 'primary_metric_rationale', 'expected_result_patterns',
            'inconclusive_criteria', 'sampling_strategy', 'purpose', 'replication_reason')}
    if isinstance(value, list):
        return sorted((normalized(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def experiment_signature(spec):
    # Purpose labels alone cannot disguise an identical scientific protocol.
    return normalized({k: getattr(spec, k) for k in ('independent_variables',
        'dependent_variables', 'controls', 'dataset_requirements', 'required_resources',
        'primary_metric', 'secondary_metrics')})


def duplicate_of(snapshot, spec):
    completed = {(r.experiment_id, r.experiment_version) for r in snapshot.runs if r.status == 'COMPLETED'}
    return next((e.experiment_id for e in snapshot.experiments if (e.experiment_id, e.version) in completed
                 and experiment_signature(e) == experiment_signature(spec)), None)


def replication_reason(spec):
    sampling = spec.dataset_requirements
    reason = sampling.get('replication_reason')
    return reason.strip() if sampling.get('purpose') == 'replication' and isinstance(reason, str) and len(reason.strip()) >= 10 else None


def hypothesis_disposition(snapshot, hypothesis):
    if not hypothesis:
        return None
    event = next((e for e in reversed(snapshot.events) if e.event_type in (
        'HYPOTHESIS_ACCEPTED_FOR_CHARTER', 'HYPOTHESIS_REJECTED') and
        e.payload.get('hypothesis_id', e.target_id) == hypothesis.hypothesis_id and
        e.payload.get('version') == hypothesis.version), None)
    return event.event_type if event else None


def telemetry(snapshot):
    kinds = {}
    for e in snapshot.events:
        kinds.setdefault(e.event_type, []).append(e)
    counts = {'papers_screened': sum(e.payload.get('screened_count', 0) for e in kinds.get('EVIDENCE_GATHERING_COMPLETED', [])),
        'deep_evidence_records': len(snapshot.evidence), 'hypotheses_considered': len({h.hypothesis_id for h in snapshot.hypotheses}),
        'experiment_candidates_considered': len({c.candidate_id for c in snapshot.candidates}),
        'experiments_executed': sum(r.status != s.RunStatus.PENDING for r in snapshot.runs),
        'completed_runs': sum(r.status == s.RunStatus.COMPLETED for r in snapshot.runs),
        'pending_run_records': sum(r.status == s.RunStatus.PENDING for r in snapshot.runs),
        'planner_decisions': len(snapshot.decisions),
        'human_approvals': len(kinds.get('HUMAN_APPROVED', [])),
        'revisions': sum('REVISED' in e.event_type for e in snapshot.events)}
    pairs = [('preparation', 'RESOURCE_PREPARATION_STARTED', 'RESOURCE_PREPARATION_COMPLETED'),
        ('implementation', 'IMPLEMENTATION_STARTED', 'IMPLEMENTATION_APPROVED'),
        ('analysis', 'RESULT_ANALYSIS_STARTED', 'RESULT_ANALYSIS_COMPLETED')]
    def stage_key(event, label):
        if label == 'analysis':
            analysis = next((a for a in snapshot.analyses if a.analysis_id == event.target_id), None)
            return event.payload.get('run_id') or (analysis.run_id if analysis else None)
        implementation = next((i for i in snapshot.implementations if i.implementation_id == event.target_id), None)
        return (event.payload.get('experiment_id') or
                (implementation.experiment_id if implementation else event.target_id))
    durations, duration_records = {}, {}
    for label, start, end in pairs:
        records = []
        starts = kinds.get(start, [])
        for index, a in enumerate(starts):
            key = stage_key(a, label)
            next_start = next((e for e in starts[index+1:] if stage_key(e, label) == key), None)
            b = next((e for e in kinds.get(end, []) if key is not None and stage_key(e, label) == key
                and e.created_at >= a.created_at and (next_start is None or e.created_at < next_start.created_at)), None)
            if b:
                records.append({'start_event': a.event_id, 'end_event': b.event_id,
                    'scope_id': key, 'seconds': (b.created_at-a.created_at).total_seconds()})
        duration_records[label] = records
        durations[label] = [r['seconds'] for r in records]
    durations['execution'] = [r.environment_metadata.get('duration_seconds') for r in snapshot.runs]
    durations['result_to_decision'] = [next(((d.created_at-r.completed_at).total_seconds()
        for d in snapshot.decisions if d.created_at >= r.completed_at), None)
        for r in snapshot.runs if r.completed_at]
    first = lambda kind: kinds.get(kind, [None])[0]
    evidence, hypothesis, experiment = first('EVIDENCE_ADDED'), first('HYPOTHESIS_CREATED'), first('EXPERIMENT_SPEC_CREATED')
    durations['question_to_first_evidence'] = (evidence.created_at-snapshot.charter.created_at).total_seconds() if evidence else None
    durations['evidence_to_hypothesis'] = (hypothesis.created_at-evidence.created_at).total_seconds() if hypothesis and evidence else None
    durations['hypothesis_to_experiment_spec'] = (experiment.created_at-hypothesis.created_at).total_seconds() if experiment and hypothesis else None
    durations['approval_waiting'] = [next(((b.created_at-a.created_at).total_seconds()
        for b in kinds.get('HUMAN_APPROVED', []) if b.created_at >= a.created_at
        and b.payload.get('packet_id') == a.payload.get('packet', {}).get('packet_id')), None)
        for a in kinds.get('HUMAN_APPROVAL_REQUESTED', [])]
    return {'counts': counts, 'durations_seconds': durations,
            'duration_records': duration_records,
            'timing_scope': 'Recorded timestamps only; stage pairs match their scientific scope; approval wait ends at the first approval of the exact packet; result-to-decision ends at the first following PI decision; missing stays unknown; no human baseline or acceleration claim'}


def decision_events(ledger, snapshot, decision, selection):
    if not snapshot.analyses:
        return []
    def event(kind, payload, summary):
        return s.EventRecord(event_id=ledger.next_id('EVENT'), project_id=decision.project_id,
            event_type=kind, actor='orchestrator', target_type='decisions', target_id=decision.decision_id,
            summary=summary, payload=payload)
    events = []
    existing = rounds(snapshot)
    if not existing:
        events.append(event('RESEARCH_ROUND_STARTED', {'round_id': 'ROUND_0001', 'index': 1,
            'started_at': snapshot.runs[0].started_at.isoformat() if snapshot.runs else None,
            'parent_round': None, 'imported_existing_work': True, **source_links(snapshot)},
            'Register existing canonical research as first round; no execution fabricated'))
    round_id = existing[-1].payload['round_id'] if existing else 'ROUND_0001'
    already_done = any(e.event_type == 'RESEARCH_ROUND_COMPLETED' and e.payload.get('round_id') == round_id for e in snapshot.events)
    # An existing round ends only when reviewed results return to PI.
    active_parent_run = existing[-1].payload.get('parent_run_id') if existing else None
    if result_packet(snapshot) and not already_done and (not existing or
        current_run(snapshot).run_id != active_parent_run or existing[-1].payload.get('imported_existing_work')):
        events.append(event('RESEARCH_ROUND_COMPLETED', {'round_id': round_id, 'ending_decision': decision.decision_id,
            **source_links(snapshot)}, 'Reviewed result returned to Planner'))
    if already_done:
        events.append(event('RESEARCH_ROUND_NEXT_DECISION', {'round_id': round_id,
            'ending_decision': decision.decision_id}, 'Planner decision after completed bounded round'))
    if decision.action == A.SELECT_EXPERIMENT and result_packet(snapshot) and (not existing or already_done):
        # PI may directly select a previously reviewed unselected candidate.
        # Its new scientific commitment still starts a new bounded iteration.
        next_index = round_count(snapshot) + 1
        new_round = f'ROUND_{next_index:04d}'
        events.append(event('RESEARCH_ROUND_STARTED', {'round_id': new_round, 'index': next_index,
            'parent_round': round_id, 'trigger_decision': decision.decision_id,
            **source_links(snapshot)}, 'Planner directly selected a reviewed follow-up; start new round'))
        for record in selection:
            if isinstance(record, s.EventRecord): record.payload['round_id'] = new_round
    projected = snapshot.model_copy(deep=True)
    for record in selection:
        if isinstance(record, s.EventRecord): projected.events.append(record)
        elif isinstance(record, s.ExperimentSpec): projected.experiments.append(record)
    events.append(event('ADAPTIVE_DECISION_CREATED', {'decision_id': decision.decision_id,
        'round_id': round_id, 'action': decision.action.value, 'target': decision.target_agent,
        'rationale': decision.reason, 'source_pin': state_pin(snapshot), 'dispatch_pin': state_pin(projected),
        'budget': calculate_budget(snapshot).model_dump(mode='json'), 'time': calculate_time(snapshot).model_dump(mode='json'),
        **source_links(snapshot)}, 'One result-informed NextDecision; no hidden reasoning persisted'))
    if decision.action == A.STOP:
        events.append(event('RESEARCH_STOPPED', {'decision_id': decision.decision_id, 'round_id': round_id,
            'reason': decision.reason, **source_links(snapshot)}, 'Planner stopped with explicit scientific/constraint rationale'))
    return events
