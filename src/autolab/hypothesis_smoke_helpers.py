"""Shared live smoke validation; scientific output stays in ignored results/."""
import json
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.evidence_smoke_helpers import verify_records
from autolab.hypotheses.validation import LABEL, SUPPORTED, INFERENCE, normalized_statement
from autolab.orchestration.state_machine import latest_versions


def verify_hypotheses(ledger, project_id, result):
    verify_records(ledger, project_id)
    hypotheses = ledger.list_hypotheses(project_id)
    reviews = ledger.list_reviews(project_id)
    events = ledger.list_records(s.EventRecord, project_id)
    latest = latest_versions(hypotheses, "hypothesis_id")
    assert len(latest) == 3 and {h.hypothesis_id for h in latest} == set(result.hypothesis_ids)
    assert len({normalized_statement(h.statement) for h in latest}) == 3
    for hypothesis in hypotheses:
        assert hypothesis.rationale.startswith(LABEL) and SUPPORTED in hypothesis.rationale and INFERENCE in hypothesis.rationale
        assert hypothesis.falsifiable_prediction
        for identifier in hypothesis.supporting_evidence_ids+hypothesis.contradicting_evidence_ids:
            evidence = ledger.get(s.EvidenceRecord, identifier)
            assert evidence and evidence.project_id == project_id
    for review in reviews:
        target = ledger.get(s.Hypothesis, review.target_id, version=review.target_version)
        assert target and target.project_id == project_id and review.reviewer_role == "critic"
    for hypothesis in latest:
        versions = [h.version for h in hypotheses if h.hypothesis_id == hypothesis.hypothesis_id]
        assert sorted(versions) == list(range(1, hypothesis.version+1))
    assert all(i in {r.review_id for r in reviews} for i in result.review_ids)
    assert any(e.event_type == "HYPOTHESIS_GENERATION_COMPLETED" for e in events)
    assert result.revision_rounds <= 1
    assert not ledger.list_experiments(project_id) and not ledger.list_experiment_candidates(project_id)
    assert not any(e.actor == "experiment_designer" for e in events)
    return hypotheses, reviews, events


def write_artifact(name, ledger, project_id, result, **extra):
    path = PROJECT_ROOT / "results" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {"project": ledger.get_project(project_id).model_dump(mode="json"),
        "sources": [r.model_dump(mode="json") for r in ledger.list_sources(project_id)],
        "evidence": [r.model_dump(mode="json") for r in ledger.list_evidence(project_id)],
        "hypotheses": [r.model_dump(mode="json") for r in ledger.list_hypotheses(project_id)],
        "reviews": [r.model_dump(mode="json") for r in ledger.list_reviews(project_id)],
        "events": [r.model_dump(mode="json") for r in ledger.list_records(s.EventRecord, project_id)],
        "decisions": [r.model_dump(mode="json") for r in ledger.list_records(s.NextDecision, project_id)],
        "workflow_result": result.model_dump(mode="json"), **extra}
    path.write_text(json.dumps(snapshot, indent=2, allow_nan=False)+"\n")
    return path


def print_candidates(ledger, result):
    for identifier in result.hypothesis_ids:
        h = ledger.get(s.Hypothesis, identifier)
        review = next(r for r in reversed(ledger.list_reviews(result.project_id)) if r.target_id == identifier)
        print(f"{identifier} version {h.version}: {h.statement}")
        print(f"Prediction: {h.falsifiable_prediction}")
        print(f"Critic: {review.verdict.value} (reviewed version {review.target_version})")
