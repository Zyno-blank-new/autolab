"""Isolated live smokes continue real scientific checkpoints without reretrieval."""
import json
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.evidence_smoke_helpers import verify_records
from autolab.experiment_design.context import build_context
from autolab.experiment_design.validation import validate_design, spec_from_candidate
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import latest_versions, latest_review, selected_hypothesis, selected_experiment
from autolab.orchestration.models import RoutingDecision


def seed_hypothesis(ledger):
    path = PROJECT_ROOT/'results/phase5-hypothesis-loop-smoke.json'
    if not path.exists():
        raise RuntimeError("Run autolab.hypothesis_loop_smoke first to create a real evidence/hypothesis checkpoint")
    data = json.loads(path.read_text())
    project = s.ResearchCharter.model_validate({**data['project'], 'created_at': s.utc_now()})
    ledger.create_project(project)
    for model, name in ((s.SourceRecord, 'sources'), (s.EvidenceRecord, 'evidence'), (s.Hypothesis, 'hypotheses'), (s.ReviewRecord, 'reviews')):
        ledger.add_many([model.model_validate(row) for row in data[name]])
    chosen = next(e for e in reversed(data['events']) if e['event_type'] == 'HYPOTHESIS_SELECTED')
    ledger.add_event(s.EventRecord.model_validate({**chosen, 'event_id': ledger.next_id('EVENT'), 'created_at': s.utc_now()}))
    # Replay the real Phase 5 PI handoff into this isolated fresh-time project.
    decision_data = next(d for d in data['decisions'] if d['decision_id'] == chosen['payload']['decision_id'])
    decision = s.NextDecision.model_validate({**decision_data, 'created_at': s.utc_now()})
    ledger.add(decision)
    verify_records(ledger, project.project_id)
    build_context(load_snapshot(ledger, project.project_id))
    return project, RoutingDecision(decision_id=decision.decision_id, action=decision.action,
        target_role=decision.target_agent, reason=decision.reason, context_requirements=decision.required_context_ids,
        control_state='EXPERIMENT_DESIGN')


def seed_design(ledger):
    path = PROJECT_ROOT/'results/phase6-experiment-design-smoke.json'
    if not path.exists():
        raise RuntimeError("Run autolab.experiment_design_integration_smoke first")
    data = json.loads(path.read_text())
    snapshot = data['snapshot']
    project = s.ResearchCharter.model_validate({**snapshot['charter'], 'created_at': s.utc_now()})
    ledger.create_project(project)
    for model, name in ((s.SourceRecord, 'sources'), (s.EvidenceRecord, 'evidence'), (s.Hypothesis, 'hypotheses'),
        (s.ExperimentCandidate, 'candidates'), (s.ReviewRecord, 'reviews'), (s.NextDecision, 'decisions'), (s.EventRecord, 'events')):
        ledger.add_many([model.model_validate(row) for row in snapshot[name]])
    verify_records(ledger, project.project_id)
    return project, data


def verify_design(ledger, project_id, result, *, selected=False):
    snapshot = load_snapshot(ledger, project_id)
    verify_records(ledger, project_id)
    hypothesis = selected_hypothesis(snapshot)
    assert hypothesis and (hypothesis.hypothesis_id, hypothesis.version) == (result.hypothesis_id, result.hypothesis_version)
    latest = latest_versions(snapshot.candidates, 'candidate_id')
    assert 2 <= len(latest) <= 3 and {c.candidate_id for c in latest} == set(result.candidate_ids)
    for c in snapshot.candidates:
        validate_design(c.design)
        assert c.hypothesis_id == hypothesis.hypothesis_id and c.hypothesis_version == hypothesis.version
        assert [x.version for x in snapshot.candidates if x.candidate_id == c.candidate_id] == list(range(1, ledger.get(s.ExperimentCandidate, c.candidate_id).version+1))
    for r in snapshot.reviews:
        if r.review_type == 'experiment':
            target = ledger.get(s.ExperimentCandidate, r.target_id, version=r.target_version)
            assert target and target.project_id == project_id and r.reviewer_role == 'critic'
    assert result.revision_rounds <= 1
    assert not snapshot.resources and not snapshot.readiness and not snapshot.implementations and not snapshot.runs and not snapshot.metrics and not snapshot.analyses
    assert not any(e.actor in ('preparation', 'readiness', 'implementer', 'code_auditor', 'experiment_runner', 'runtime') for e in snapshot.events)
    if selected:
        assert len(snapshot.experiments) == 1
        spec = selected_experiment(snapshot)
        event = next(e for e in reversed(snapshot.events) if e.event_type == 'EXPERIMENT_SELECTED')
        candidate = ledger.get(s.ExperimentCandidate, event.payload['candidate_id'], version=event.payload['candidate_version'])
        review = ledger.get(s.ReviewRecord, event.payload['review_id'])
        assert review.verdict == s.ReviewVerdict.PASS and review.target_id == candidate.candidate_id and review.target_version == candidate.version
        assert event.payload['hypothesis_id'] == hypothesis.hypothesis_id
        projection = spec_from_candidate(candidate, spec.experiment_id)
        assert spec.model_dump(exclude={'created_at'}) == projection.model_dump(exclude={'created_at'})
        assert spec.primary_metric and spec.success_criteria and spec.falsification_criteria and spec.status == s.ExperimentStatus.PREREGISTERED
        decision = ledger.get(s.NextDecision, event.payload['decision_id'])
        assert decision.reason == event.payload['reason'] and candidate.candidate_id in decision.required_context_ids
        assert spec.created_at > review.created_at
    else:
        assert not snapshot.experiments
    return snapshot


def artifact(name, ledger, project_id, result, **extra):
    path = PROJECT_ROOT/'results'/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'snapshot': load_snapshot(ledger, project_id).model_dump(mode='json'),
        'workflow_result': result.model_dump(mode='json'), **extra}, indent=2, allow_nan=False)+'\n')
    return path


def print_candidates(snapshot):
    for c in latest_versions(snapshot.candidates, 'candidate_id'):
        review = next(r for r in reversed(snapshot.reviews) if r.review_type == 'experiment' and r.target_id == c.candidate_id)
        print(f"{c.candidate_id} version {c.version}: {c.title}")
        print(f"Primary metric: {c.design['primary_metric']}")
        print(f"Critic: {review.verdict.value} (evaluated version {review.target_version})")
