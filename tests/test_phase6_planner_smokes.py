"""Separate adaptive decisions from deterministic selection-path coverage."""
import asyncio
import json

import pytest

from autolab import schemas as s
from autolab.experiment_design.validation import spec_from_candidate
from autolab.experiment_selection_smoke_helpers import (
    SELECTION_READY_FIXTURE, seed_selection_ready, selection_outcome, verify_planner_outcome,
)
from autolab.ledger import ResearchLedger
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.orchestrator import IllegalDecisionError, Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_experiment, selected_hypothesis
from autolab.planner.service import PlannerOutputError


class DecisionPlanner:
    """Only the Planner decision is mocked; the canonical control plane is real."""
    def __init__(self, action, candidate_id=None, target=None, malformed=False):
        self.action, self.candidate_id, self.target = action, candidate_id, target
        self.malformed, self.calls, self.contexts = malformed, 0, []

    async def propose(self, context, decision_id, feedback=None):
        self.calls += 1
        self.contexts.append(context)
        if self.malformed:
            return "not structured JSON"
        return s.NextDecision(decision_id=decision_id, project_id=context.charter.project_id,
            action=self.action, target_agent=self.target or {
                "GATHER_EVIDENCE": "evidence", "SELECT_EXPERIMENT": "planner"}.get(self.action),
            reason=("Verify whether prior comparisons matched tool-call budgets; abstracts do not establish this."
                    if self.action == "GATHER_EVIDENCE" else "Compare the selected proposal's primary estimand and controls."),
            required_context_ids=[self.candidate_id] if self.candidate_id else [],
            remaining_budget_usd=context.budget.remaining_budget_usd).model_dump_json()


def test_selection_fixture_preserves_real_evidence_and_exact_review_versions(ledger):
    project, provenance = seed_selection_ready(ledger)
    snapshot = load_snapshot(ledger, project.project_id)
    original = json.loads(SELECTION_READY_FIXTURE.read_text())["snapshot"]
    assert provenance["source_checkpoint_sha256"]
    assert snapshot.charter.project_id == "PROJECT_SELECTION_READY"
    assert snapshot.charter.objective != "Assess prior evidence on agent recovery reliability under fixed tool-call budgets."
    assert len(snapshot.sources) == 3 and len(snapshot.evidence) == 6
    assert all(e.location == "abstract" and "ABSTRACT_ONLY" in e.tags for e in snapshot.evidence)
    assert [e.model_dump(mode="json") for e in snapshot.evidence] == original["evidence"]
    hypothesis = selected_hypothesis(snapshot)
    assert hypothesis and hypothesis.version == 1
    assert len(snapshot.candidates) == 2
    for candidate in snapshot.candidates:
        reviews = [r for r in snapshot.reviews if r.review_type == "experiment" and r.target_id == candidate.candidate_id]
        assert len(reviews) == 1 and reviews[0].verdict == "PASS" and reviews[0].target_version == candidate.version
    context = ContextBuilder().build(snapshot)
    assert {"GATHER_EVIDENCE", "SELECT_EXPERIMENT"} <= {a.value for a in context.available_actions}


@pytest.mark.parametrize("candidate_id", ["CAND_0001", "CAND_0002"])
def test_deterministic_selection_path_from_reviewed_canonical_state(ledger, candidate_id):
    project, _ = seed_selection_ready(ledger)
    before = load_snapshot(ledger, project.project_id)
    planner = DecisionPlanner("SELECT_EXPERIMENT", candidate_id)
    route = asyncio.run(Orchestrator(ledger, planner).decide(project.project_id))
    after = verify_planner_outcome(ledger, before, route)
    candidate = ledger.get(s.ExperimentCandidate, candidate_id)
    experiment = selected_experiment(after)
    assert planner.calls == 1
    assert len(planner.contexts[0].summaries["candidates"]) == 2
    assert experiment.title == candidate.title
    assert len(after.experiments) == 1 and after.candidates == before.candidates
    assert after.reviews == before.reviews
    assert experiment.primary_metric == candidate.design["primary_metric"]
    assert experiment.success_criteria and experiment.falsification_criteria
    assert selection_outcome(route, selection_ready=True) == "PASS"
    assert route.control_state.value == "AWAITING_HUMAN_APPROVAL"
    with ResearchLedger(ledger.database.path) as reopened:
        assert verify_planner_outcome(reopened, before, route) == after


@pytest.mark.parametrize("action", ["GATHER_EVIDENCE", "STOP", "DESIGN_EXPERIMENT"])
def test_legal_adaptive_divergence_persists_without_fabricating_selection(ledger, action):
    project, _ = seed_selection_ready(ledger)
    before = load_snapshot(ledger, project.project_id)
    if action == "DESIGN_EXPERIMENT":
        # A legal design route pins the selected hypothesis, not an experiment.
        class DesignPlanner(DecisionPlanner):
            async def propose(self, context, decision_id, feedback=None):
                return s.NextDecision(decision_id=decision_id, project_id=context.charter.project_id,
                    action=action, target_agent="experiment_designer", reason="Investigate a smaller complementary design",
                    required_context_ids=[selected_hypothesis(before).hypothesis_id],
                    remaining_budget_usd=context.budget.remaining_budget_usd).model_dump_json()
        planner = DesignPlanner(action)
    else:
        planner = DecisionPlanner(action)
    route = asyncio.run(Orchestrator(ledger, planner).decide(project.project_id))
    after = verify_planner_outcome(ledger, before, route)
    assert route.action.value == action
    assert selection_outcome(route, selection_ready=False) == "PASS"
    assert selection_outcome(route, selection_ready=True) == "LEGAL_DIVERGENCE"
    assert not after.experiments
    assert after.decisions[-1].reason == route.reason
    assert any(e.event_type == "PLANNER_DECISION" and e.target_id == route.decision_id for e in after.events)


@pytest.mark.parametrize("case", ["wrong_role", "unknown_candidate", "malformed"])
def test_smoke_semantics_do_not_relax_production_validation(ledger, case):
    project, _ = seed_selection_ready(ledger)
    before = load_snapshot(ledger, project.project_id)
    planner = (DecisionPlanner("SELECT_EXPERIMENT", "CAND_UNKNOWN") if case == "unknown_candidate"
               else DecisionPlanner("GATHER_EVIDENCE", target="planner", malformed=case == "malformed"))
    error = PlannerOutputError if case == "malformed" else IllegalDecisionError
    with pytest.raises(error):
        asyncio.run(Orchestrator(ledger, planner).decide(project.project_id))
    assert planner.calls == 2
    assert load_snapshot(ledger, project.project_id) == before


def test_adaptive_outcome_check_detects_fabricated_experiment(ledger):
    project, _ = seed_selection_ready(ledger)
    before = load_snapshot(ledger, project.project_id)
    route = asyncio.run(Orchestrator(ledger, DecisionPlanner("GATHER_EVIDENCE")).decide(project.project_id))
    ledger.add_experiment_spec(spec_from_candidate(before.candidates[0], "EXP_FABRICATED"))
    with pytest.raises(AssertionError):
        verify_planner_outcome(ledger, before, route)
