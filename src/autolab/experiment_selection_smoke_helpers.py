"""Smoke-only state and outcome checks; production Planner rules are unchanged."""
import json

from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.evidence_smoke_helpers import verify_records
from autolab.experiment_design.context import build_context
from autolab.experiment_design.validation import spec_from_candidate, validate_design
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import (
    latest_review, latest_versions, selected_experiment, selected_hypothesis,
)

SELECTION_READY_FIXTURE = PROJECT_ROOT / "tests/fixtures/phase6_selection_ready.json"


def verify_no_execution(snapshot):
    for name in ("resources", "readiness", "implementations", "runs", "metrics", "analyses"):
        assert not getattr(snapshot, name), f"Smoke crossed its boundary: {name}"
    assert not any(e.actor in ("preparation", "readiness", "implementer", "code_auditor",
                              "experiment_runner", "runtime") for e in snapshot.events)


def seed_selection_ready(ledger, fixture_path=SELECTION_READY_FIXTURE):
    """Load a fresh empirical project without changing the original charter.

    Real saved evidence, proposals and reviews retain their scientific contents.
    Abstracts motivate a local empirical question; they do not establish a local
    effect, audited resources, sample adequacy or approval to spend or execute.
    """
    data = json.loads(fixture_path.read_text())
    snapshot = data["snapshot"]
    for name in ("experiments", "resources", "readiness", "implementations", "runs", "metrics", "analyses", "costs"):
        assert not snapshot[name], f"Selection fixture must precede {name}"
    project = ledger.create_project(s.ResearchCharter.model_validate(
        {**snapshot["charter"], "created_at": s.utc_now()}))
    for model, name in ((s.SourceRecord, "sources"), (s.EvidenceRecord, "evidence"),
                        (s.Hypothesis, "hypotheses"), (s.ExperimentCandidate, "candidates"),
                        (s.ReviewRecord, "reviews"), (s.NextDecision, "decisions"),
                        (s.EventRecord, "events")):
        ledger.add_many([model.model_validate(row) for row in snapshot[name]])
    verify_records(ledger, project.project_id)
    loaded = load_snapshot(ledger, project.project_id)
    context = build_context(loaded)
    assert context.hypothesis_review.verdict == s.ReviewVerdict.PASS
    candidates = latest_versions(loaded.candidates, "candidate_id")
    assert len(candidates) == 2
    for candidate in candidates:
        validate_design(candidate.design)
        assert candidate.project_id == project.project_id
        assert (candidate.hypothesis_id, candidate.hypothesis_version) == (
            context.hypothesis.hypothesis_id, context.hypothesis.version)
        review = latest_review(loaded, s.ExperimentCandidate, candidate.candidate_id,
                              candidate.version, "experiment")
        assert review and review.verdict == s.ReviewVerdict.PASS and review.reviewer_role == "critic"
        proposed = s.NextDecision(decision_id="DEC_READINESS_CHECK", project_id=project.project_id,
            action="SELECT_EXPERIMENT", target_agent="planner", reason="Offline legality check only",
            required_context_ids=[candidate.candidate_id], remaining_budget_usd=project.budget_usd)
        assert DecisionValidator().validate(proposed, loaded).valid
    verify_no_execution(loaded)
    return project, data["provenance"]


def verify_planner_outcome(ledger, before, route):
    """Accept any normally validated action; verify selection only if it occurred."""
    after = load_snapshot(ledger, before.charter.project_id)
    decision = ledger.get(s.NextDecision, route.decision_id)
    assert decision and decision.project_id == before.charter.project_id
    assert (decision.action, decision.target_agent, decision.reason) == (
        route.action, route.target_role, route.reason)
    assert DecisionValidator().validate(decision, before, expected_decision_id=route.decision_id).valid
    assert len(after.decisions) == len(before.decisions) + 1 and after.decisions[-1] == decision
    events = [e for e in after.events if e.event_type == "PLANNER_DECISION"
              and e.payload.get("decision_id") == decision.decision_id]
    assert len(events) == 1 and events[0].target_id == decision.decision_id and events[0].actor == "planner"
    assert events[0].payload["action"] == decision.action.value
    assert events[0].payload["target_role"] == decision.target_agent
    assert events[0].payload["required_context_ids"] == decision.required_context_ids
    assert after.charter == before.charter
    for name in ("sources", "evidence", "hypotheses", "candidates", "reviews"):
        assert getattr(after, name) == getattr(before, name)
    selections = [e for e in after.events if e.event_type == "EXPERIMENT_SELECTED"
                  and e.payload.get("decision_id") == decision.decision_id]
    if decision.action == s.PlannerAction.SELECT_EXPERIMENT:
        assert not before.experiments and len(after.experiments) == 1 and len(selections) == 1
        selection = selections[0]
        candidate = ledger.get(s.ExperimentCandidate, selection.payload["candidate_id"],
                               version=selection.payload["candidate_version"])
        hypothesis = selected_hypothesis(before)
        assert candidate and hypothesis and candidate.project_id == decision.project_id
        assert (candidate.hypothesis_id, candidate.hypothesis_version) == (
            hypothesis.hypothesis_id, hypothesis.version)
        assert [candidate.candidate_id] == [i for i in decision.required_context_ids if i.startswith("CAND_")]
        review = ledger.get(s.ReviewRecord, selection.payload["review_id"])
        assert review and review.verdict == s.ReviewVerdict.PASS and review.reviewer_role == "critic"
        assert (review.target_id, review.target_version) == (candidate.candidate_id, candidate.version)
        assert review.project_id == candidate.project_id
        experiment = selected_experiment(after)
        assert experiment and experiment.status == s.ExperimentStatus.PREREGISTERED
        projection = spec_from_candidate(candidate, experiment.experiment_id)
        assert experiment.model_dump(exclude={"created_at"}) == projection.model_dump(exclude={"created_at"})
        assert experiment.primary_metric and experiment.success_criteria and experiment.falsification_criteria
        assert experiment.created_at > review.created_at
        assert selection.payload["reason"] == decision.reason
        alternatives = {c.candidate_id for c in latest_versions(before.candidates, "candidate_id")
                        if (c.hypothesis_id, c.hypothesis_version) == (
                            candidate.hypothesis_id, candidate.hypothesis_version)
                        and c.candidate_id != candidate.candidate_id}
        assert set(selection.payload["non_selected_candidate_ids"]) == alternatives and alternatives
        spec_events = [e for e in after.events if e.event_type == "EXPERIMENT_SPEC_CREATED"
                       and e.payload.get("decision_id") == decision.decision_id]
        assert len(spec_events) == 1 and spec_events[0].payload == selection.payload
        assert route.control_state.value == "AWAITING_HUMAN_APPROVAL"
    else:
        assert not selections and after.experiments == before.experiments
        types = ("EXPERIMENT_SELECTED", "EXPERIMENT_SPEC_CREATED")
        assert [e for e in after.events if e.event_type in types] == [e for e in before.events if e.event_type in types]
    verify_no_execution(after)
    return after


def selection_outcome(route, *, selection_ready):
    # Legal divergence is a scientific choice, not a failed system test.
    return ("LEGAL_DIVERGENCE" if selection_ready
            and route.action != s.PlannerAction.SELECT_EXPERIMENT else "PASS")
