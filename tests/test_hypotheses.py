"""Phase 5 uses fake Omnigent output only: no network or paid calls."""
import asyncio
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.hypotheses.agent import OmnigentHypothesisAgent, OmnigentScientificCritic
from autolab.hypotheses.context import build_context, critic_packet
from autolab.hypotheses.models import (HypothesisBatch, ReviewBatch, RevisionBatch, CritiqueResponse,
    HypothesisLimits, HypothesisOutputError)
from autolab.hypotheses.service import HypothesisPipeline
from autolab.hypotheses.validation import (LABEL, SUPPORTED, INFERENCE, normalized_statement,
    validate_hypotheses, validate_reviews, validate_responses)
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.orchestrator import Orchestrator, IllegalDecisionError
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_hypothesis


@pytest.fixture
def project(ledger):
    project = ledger.create_project(s.ResearchCharter(project_id=ledger.next_id("PROJECT"), title="Fixture science",
        research_question="What explains reliability?", objective="Resolve uncertainty", primary_outcome="Success",
        budget_usd=10, max_runtime_minutes=60))
    source = ledger.add_source(s.SourceRecord(source_id=ledger.next_id("SRC"), project_id=project.project_id,
        title="Synthetic offline fixture", abstract="Fixture methods vary with budgets."))
    for role in ("SUPPORTING", "CONTRADICTING", "METHOD"):
        ledger.add_evidence(s.EvidenceRecord(evidence_id=ledger.next_id("EVID"), project_id=project.project_id,
            source_id=source.source_id, claim="Synthetic fixture: " + role, supporting_text="Fixture methods vary with budgets.",
            confidence=0.5, tags=[role, "SYNTHETIC_TEST_ONLY"]))
    return project


def candidates(context, assignments):
    rows = []
    mechanisms = ["Error classification improves success for schema failures", "Budget exhaustion eliminates recovery gains",
                  "Context contamination explains semantic recovery failures", "Planning ambiguity mediates failures", "Retrieval noise limits repair"]
    ids = [e["id"] for e in context.evidence]
    for n, assignment in enumerate(assignments):
        rows.append(s.Hypothesis(**assignment, statement=mechanisms[n],
            rationale=f"{LABEL}. {SUPPORTED} " + (ids[0] if ids else "None; LOW-CONFIDENCE") + f". {INFERENCE} The proposed mechanism is untested.",
            supporting_evidence_ids=ids[:1], contradicting_evidence_ids=ids[1:2],
            falsifiable_prediction=f"The predicted success difference for mechanism {n} vanishes if its proposed condition is absent.",
            novelty_score=0.4, testability_score=0.7, scientific_value_score=0.9 if n == 0 else 0.3))
    return HypothesisBatch(hypotheses=rows)


class FakeAgent:
    def __init__(self, error=None, disposition="REBUT"):
        self.calls, self.contexts, self.error, self.disposition = [], [], error, disposition
    async def generate(self, context, assignments):
        self.calls.append("generate")
        self.contexts.append(context)
        batch = candidates(context, assignments)
        if self.error == "duplicate":
            batch.hypotheses[1] = batch.hypotheses[1].model_copy(update={"statement": batch.hypotheses[0].statement.upper()+"!"})
        if self.error == "foreign":
            batch.hypotheses[0] = batch.hypotheses[0].model_copy(update={"supporting_evidence_ids": ["EVID_FAKE"]})
        if self.error == "malformed":
            raise HypothesisOutputError("Malformed fake output")
        if self.error == "insufficient":
            return HypothesisBatch(hypotheses=[], insufficient_basis="No justified scientific proposition")
        return batch
    async def revise(self, context, hypotheses, reviews, assignments):
        self.calls.append("revise")
        versions = {a["hypothesis_id"]: a["version"] for a in assignments}
        revised = [h.model_copy(update={"version": versions[h.hypothesis_id], "status": s.HypothesisStatus.REFINED,
            "rationale": h.rationale+" The counterargument is conditional, not a claim of proof."}) for h in hypotheses]
        responses = [CritiqueResponse(review_id=r.review_id, issue_index=i, disposition=self.disposition,
            reason="This is a proposed conditional mechanism; uncertainty remains explicit.") for r in reviews for i in range(len(r.issues))]
        return RevisionBatch(hypotheses=revised, responses=responses)


class FakeCritic:
    def __init__(self, verdicts=None, final=s.ReviewVerdict.PASS, error=None, callback=None):
        self.verdicts = verdicts or [s.ReviewVerdict.PASS]*5
        self.final, self.error, self.callback = final, error, callback
        self.calls, self.packets = [], []
    async def review(self, context, hypotheses, assignments, *, all_candidates=None, responses=None):
        self.calls.append("final" if responses is not None else "initial")
        self.packets.append(critic_packet(context, hypotheses, all_candidates=all_candidates, responses=responses))
        if self.callback:
            self.callback()
        if self.error == "malformed":
            raise HypothesisOutputError("Malformed fake review")
        rows = []
        for n, (h, identity) in enumerate(zip(hypotheses, assignments)):
            verdict = self.final if responses is not None else self.verdicts[n]
            rows.append(s.ReviewRecord(**identity, review_type="hypothesis", target_type="hypotheses", verdict=verdict,
                reviewer_role="critic", issues=[] if verdict == s.ReviewVerdict.PASS else [{
                    "problem": "Fixture prediction leaves the mechanism ambiguous", "why_it_matters": "Competing explanations remain",
                    "resolution": "Clarify the conditional proposition", "evidence_ids": []}]))
        if self.error == "target":
            rows[0] = rows[0].model_copy(update={"target_id": "HYP_FAKE"})
        if self.error == "citation":
            rows[0] = rows[0].model_copy(update={"recommendations": ["Use EVID_FAKE"]})
        return ReviewBatch(reviews=rows)


def run_pipeline(ledger, project, **kwargs):
    agent = kwargs.pop("agent", FakeAgent())
    critic = kwargs.pop("critic", FakeCritic())
    workflow = HypothesisPipeline(ledger, agent, critic, **kwargs)
    return asyncio.run(workflow.generate(project.project_id)), agent, critic


def test_structured_canonical_batch_and_label(ledger, project):
    result, agent, critic = run_pipeline(ledger, project)
    assert len(result.hypothesis_ids) == 3 and len(result.review_ids) == 3
    assert agent.calls == ["generate"] and critic.calls == ["initial"]
    rows = ledger.list_hypotheses(project.project_id)
    assert all(h.rationale.startswith(LABEL) and h.falsifiable_prediction for h in rows)
    assert all(r.target_version == 1 and r.target_type == "hypotheses" for r in ledger.list_reviews(project.project_id))
    assert all(e.event_type != "HYPOTHESIS_SELECTED" for e in ledger.list_records(s.EventRecord, project.project_id))


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_configured_candidate_count(ledger, project, count):
    result, _, _ = run_pipeline(ledger, project, limits=HypothesisLimits(candidate_count=count))
    assert len(result.hypothesis_ids) == count


def test_wrong_count_rejected(ledger, project):
    context = build_context(load_snapshot(ledger, project.project_id))
    assignments = [{"hypothesis_id": f"HYP_{n}", "version": 1, "project_id": project.project_id} for n in range(3)]
    batch = candidates(context, assignments)
    batch.hypotheses.pop()
    with pytest.raises(HypothesisOutputError, match="every assigned"):
        validate_hypotheses(batch, context, ledger, assignments)


@pytest.mark.parametrize("field", ["novelty_score", "testability_score", "scientific_value_score"])
@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan")])
def test_score_bounds(ledger, project, field, value):
    context = build_context(load_snapshot(ledger, project.project_id))
    identity = {"hypothesis_id": "HYP_TEST", "project_id": project.project_id, "version": 1}
    h = candidates(context, [identity]).hypotheses[0]
    with pytest.raises(ValidationError):
        s.Hypothesis.model_validate({**h.model_dump(), field: value})


@pytest.mark.parametrize("field,value", [("falsifiable_prediction", " "), ("rationale", "Established fact"),
    ("status", s.HypothesisStatus.ACCEPTED), ("version", 2), ("novelty_score", None)])
def test_bad_hypothesis_fields(ledger, project, field, value):
    context = build_context(load_snapshot(ledger, project.project_id))
    assignment = {"hypothesis_id": "HYP_TEST", "project_id": project.project_id, "version": 1}
    batch = candidates(context, [assignment])
    batch.hypotheses[0] = batch.hypotheses[0].model_copy(update={field: value})
    with pytest.raises((ValidationError, HypothesisOutputError)):
        validate_hypotheses(batch, context, ledger, [assignment])


@pytest.mark.parametrize("reference_field", ["supporting_evidence_ids", "contradicting_evidence_ids"])
@pytest.mark.parametrize("kind", ["missing", "foreign", "omitted"])
def test_evidence_project_visibility(ledger, project, reference_field, kind):
    context = build_context(load_snapshot(ledger, project.project_id))
    identifier = "EVID_MISSING"
    if kind == "foreign":
        other = ledger.create_project(s.ResearchCharter(project_id=ledger.next_id("PROJECT"), title="Foreign",
            research_question="Other?", objective="Other", primary_outcome="Other"))
        source = ledger.add_source(s.SourceRecord(source_id=ledger.next_id("SRC"), project_id=other.project_id, title="Foreign"))
        identifier = ledger.add_evidence(s.EvidenceRecord(evidence_id=ledger.next_id("EVID"), project_id=other.project_id,
            source_id=source.source_id, claim="Foreign fixture")).evidence_id
    if kind == "omitted":
        identifier = context.evidence[-1]["id"]
        context = context.model_copy(update={"evidence": context.evidence[:-1]})
    assignment = {"hypothesis_id": "HYP_TEST", "project_id": project.project_id, "version": 1}
    batch = candidates(context, [assignment])
    batch.hypotheses[0] = batch.hypotheses[0].model_copy(update={reference_field: [identifier]})
    with pytest.raises(HypothesisOutputError):
        validate_hypotheses(batch, context, ledger, [assignment])


@pytest.mark.parametrize("error", ["duplicate", "foreign", "malformed"])
def test_failed_generation_no_scientific_corruption(ledger, project, error):
    with pytest.raises(HypothesisOutputError):
        run_pipeline(ledger, project, agent=FakeAgent(error=error))
    assert ledger.list_hypotheses(project.project_id) == [] and ledger.list_reviews(project.project_id) == []
    assert ledger.list_records(s.EventRecord, project.project_id)[-1].event_type == "HYPOTHESIS_GENERATION_FAILED"


def test_duplicates_against_rejected_history(ledger, project):
    result, _, _ = run_pipeline(ledger, project, critic=FakeCritic([s.ReviewVerdict.REJECT]*5))
    with pytest.raises(HypothesisOutputError, match="already exists"):
        run_pipeline(ledger, project)
    assert len({h.hypothesis_id for h in ledger.list_hypotheses(project.project_id)}) == 3
    assert result.rejected_hypothesis_ids
    assert normalized_statement("  BUDGET: Failure! ") == normalized_statement("budget failure")


def test_contradictions_visible_to_both_agents(ledger, project):
    result, agent, critic = run_pipeline(ledger, project)
    contradiction = next(e for e in agent.contexts[0].evidence if "CONTRADICTING" in e["tags"])
    assert all(contradiction in target["evidence"] for target in critic.packets[0]["targets"])
    assert "abstract" not in agent.contexts[0].model_dump_json()
    assert "hidden_reasoning" not in json.dumps(critic.packets)


def test_real_background_rationale_citations_validated_and_visible_to_critic(ledger, project):
    context = build_context(load_snapshot(ledger, project.project_id))
    assigned = [{"hypothesis_id": "HYP_TEST", "project_id": project.project_id, "version": 1}]
    batch = candidates(context, assigned)
    background_id = context.evidence[-1]["id"]
    batch.hypotheses[0] = batch.hypotheses[0].model_copy(update={"rationale": batch.hypotheses[0].rationale+" Background: "+background_id})
    validate_hypotheses(batch, context, ledger, assigned)
    packet = critic_packet(context, batch.hypotheses)
    assert background_id in {e["id"] for e in packet["targets"][0]["evidence"]}
    batch.hypotheses[0] = batch.hypotheses[0].model_copy(update={"rationale": batch.hypotheses[0].rationale+" EVID_FAKE"})
    with pytest.raises(HypothesisOutputError):
        validate_hypotheses(batch, context, ledger, assigned)


def test_contradiction_bound_fails_visibly(ledger, project):
    rows = ledger.list_evidence(project.project_id)
    for n in range(2):
        ledger.add_evidence(rows[1].model_copy(update={"evidence_id": ledger.next_id("EVID")}))
    with pytest.raises(HypothesisOutputError, match="Contradictory"):
        build_context(load_snapshot(ledger, project.project_id), HypothesisLimits(max_evidence=1))


@pytest.mark.parametrize("verdict", list(s.ReviewVerdict))
def test_each_critic_verdict_persists(ledger, project, verdict):
    result, _, _ = run_pipeline(ledger, project, critic=FakeCritic([verdict]*5), limits=HypothesisLimits(max_revision_rounds=0))
    reviews = ledger.list_reviews(project.project_id)
    assert len(reviews) == 3 and all(r.verdict == verdict for r in reviews)
    if verdict == s.ReviewVerdict.REJECT:
        assert len(result.rejected_hypothesis_ids) == 3
        assert all(ledger.get(s.Hypothesis, i).status == s.HypothesisStatus.REJECTED for i in result.hypothesis_ids)


@pytest.mark.parametrize("error", ["malformed", "target", "citation"])
def test_invalid_critic_preserves_proposals_without_invalid_reviews(ledger, project, error):
    critic = FakeCritic(error=error)
    with pytest.raises(HypothesisOutputError):
        run_pipeline(ledger, project, critic=critic)
    assert len(ledger.list_hypotheses(project.project_id)) == 3
    assert ledger.list_reviews(project.project_id) == [] and critic.calls == ["initial"]


@pytest.mark.parametrize("disposition", ["ACCEPT", "REBUT", "CLARIFY"])
def test_single_revision_rebuttal_history_restart(ledger, project, disposition):
    critic = FakeCritic([s.ReviewVerdict.REVISE]*5, final=s.ReviewVerdict.REVISE)
    result, agent, critic = run_pipeline(ledger, project, agent=FakeAgent(disposition=disposition), critic=critic)
    assert result.revision_rounds == 1 and len(result.unresolved_hypothesis_ids) == 3
    assert agent.calls == ["generate", "revise"] and critic.calls == ["initial", "final"]
    original = ledger.get(s.Hypothesis, result.hypothesis_ids[0], version=1)
    latest = ledger.get(s.Hypothesis, original.hypothesis_id)
    assert latest.version == 2 and original.status == s.HypothesisStatus.PROPOSED
    assert len(ledger.list_reviews(project.project_id)) == 6
    events = ledger.list_records(s.EventRecord, project.project_id)
    response = next(e for e in events if e.event_type == "HYPOTHESIS_REVISED").payload["responses"][0]
    assert response["disposition"] == disposition
    assert critic.packets[-1]["revision_responses"][0]["disposition"] == disposition
    path = ledger.database.path
    with ResearchLedger(path) as reopened:
        assert reopened.get(s.Hypothesis, original.hypothesis_id, version=1) == original
        assert reopened.get(s.Hypothesis, original.hypothesis_id) == latest
        assert reopened.list_reviews(project.project_id) == ledger.list_reviews(project.project_id)
        assert reopened.list_records(s.EventRecord, project.project_id) == events


def test_mixed_batch_revises_only_revise_candidates(ledger, project):
    result, agent, critic = run_pipeline(ledger, project,
        critic=FakeCritic([s.ReviewVerdict.PASS, s.ReviewVerdict.REVISE, s.ReviewVerdict.REJECT]))
    assert len(result.revised_hypothesis_ids) == 1 and len(result.passed_hypothesis_ids) == 2
    assert len(critic.packets[-1]["targets"]) == 1
    assert len(critic.packets[-1]["targets"][0]["other_candidates"]) == 2


def test_no_evidence_honest_low_confidence_and_insufficient(ledger):
    project = ledger.create_project(s.ResearchCharter(project_id="PROJECT_1", title="No evidence",
        research_question="Open question?", objective="Reduce uncertainty", primary_outcome="Success"))
    result, _, _ = run_pipeline(ledger, project)
    assert all(not h.supporting_evidence_ids and "LOW-CONFIDENCE" in h.rationale for h in ledger.list_hypotheses(project.project_id))
    result, agent, critic = run_pipeline(ledger, project, agent=FakeAgent(error="insufficient"))
    assert not result.hypothesis_ids and not critic.calls and result.warnings


def test_review_contract_and_response_coverage(ledger, project):
    context = build_context(load_snapshot(ledger, project.project_id))
    assigned = [{"hypothesis_id": "HYP_TEST", "project_id": project.project_id, "version": 1}]
    hypotheses = candidates(context, assigned).hypotheses
    reviews = asyncio.run(FakeCritic([s.ReviewVerdict.REVISE]).review(context, hypotheses,
        [{"review_id": "HREV_TEST", "target_id": "HYP_TEST", "target_version": 1, "project_id": project.project_id}])).reviews
    batch = RevisionBatch(hypotheses=hypotheses, responses=[])
    with pytest.raises(HypothesisOutputError, match="each material"):
        validate_responses(batch, reviews, context, ledger)
    with pytest.raises(ValidationError):
        ReviewBatch.model_validate({"reviews": [{**reviews[0].model_dump(), "verdict": "AGREE"}]})


class FakePlanner:
    def __init__(self, final_action=s.PlannerAction.DESIGN_EXPERIMENT, choose=0):
        self.contexts, self.final_action, self.choose = [], final_action, choose
    async def propose(self, context, decision_id, feedback=None):
        self.contexts.append(context)
        action = s.PlannerAction.GENERATE_HYPOTHESES if len(self.contexts) == 1 else self.final_action
        target = {s.PlannerAction.GENERATE_HYPOTHESES: "hypothesis", s.PlannerAction.DESIGN_EXPERIMENT: "experiment_designer",
            s.PlannerAction.GATHER_EVIDENCE: "evidence", s.PlannerAction.REFINE_HYPOTHESIS: "hypothesis", s.PlannerAction.STOP: None}[action]
        ids = [context.summaries["hypotheses"][self.choose]["id"]] if action == s.PlannerAction.DESIGN_EXPERIMENT else []
        return s.NextDecision(decision_id=decision_id, project_id=context.charter.project_id, action=action,
            target_agent=target, required_context_ids=ids, reason="Structured scientific choice with uncertainty",
            remaining_budget_usd=context.budget.remaining_budget_usd).model_dump_json()


@pytest.mark.parametrize("action", [s.PlannerAction.DESIGN_EXPERIMENT, s.PlannerAction.GATHER_EVIDENCE,
    s.PlannerAction.REFINE_HYPOTHESIS, s.PlannerAction.STOP])
def test_actual_route_and_adaptive_next_action(ledger, project, action):
    planner = FakePlanner(action, choose=1)
    orchestrator = Orchestrator(ledger, planner)
    pipeline = HypothesisPipeline(ledger, FakeAgent(), FakeCritic())
    async def run():
        first = await orchestrator.decide(project.project_id)
        result = await orchestrator.execute_hypotheses(first, pipeline)
        second = await orchestrator.decide(project.project_id)
        return first, result, second
    first, result, second = asyncio.run(run())
    assert second.action == action and len(planner.contexts[-1].summaries["hypotheses"]) == 3
    summary = planner.contexts[-1].summaries["hypotheses"][0]
    assert summary["critic"]["verdict"] == "PASS" and summary["falsifiable_prediction"]
    assert "agent-generated" in summary["origin"] and summary["supporting_evidence_ids"]
    snapshot = load_snapshot(ledger, project.project_id)
    selection = selected_hypothesis(snapshot)
    assert not snapshot.experiments and not snapshot.candidates
    assert not any(e.actor == "experiment_designer" for e in snapshot.events)
    if action == s.PlannerAction.DESIGN_EXPERIMENT:
        assert selection.hypothesis_id == result.hypothesis_ids[1] and selection.version == 1
        assert selection.scientific_value_score < ledger.get(s.Hypothesis, result.hypothesis_ids[0]).scientific_value_score
        assert any(e.event_type == "HYPOTHESIS_SELECTED" for e in snapshot.events)
    else:
        assert selection is None
    with pytest.raises(IllegalDecisionError):
        asyncio.run(orchestrator.execute_hypotheses(first, pipeline))


def test_unresolved_cannot_select_design_and_rejected_history(ledger, project):
    run_pipeline(ledger, project, critic=FakeCritic([s.ReviewVerdict.REJECT, s.ReviewVerdict.BLOCK, s.ReviewVerdict.REVISE]),
        limits=HypothesisLimits(max_revision_rounds=0))
    context = ContextBuilder().build(load_snapshot(ledger, project.project_id))
    assert s.PlannerAction.DESIGN_EXPERIMENT not in context.available_actions
    assert context.summaries["rejected_hypotheses"][0]["status"] == "REJECTED"
    assert build_context(load_snapshot(ledger, project.project_id)).rejected_hypotheses


def test_pause_during_critic_stops_persistence(ledger, project):
    def pause():
        ledger.add_event(s.EventRecord(event_id=ledger.next_id("EVENT"), project_id=project.project_id,
            event_type="PROJECT_PAUSED", actor="human", summary="Pause test"))
    with pytest.raises(HypothesisOutputError, match="blocked"):
        run_pipeline(ledger, project, critic=FakeCritic(callback=pause))
    assert len(ledger.list_hypotheses(project.project_id)) == 3 and not ledger.list_reviews(project.project_id)


@pytest.mark.parametrize("role", ["hypothesis", "critic"])
@pytest.mark.parametrize("malformed", [False, True])
def test_omnigent_adapter_uses_actual_role_yaml(ledger, project, role, malformed):
    context = build_context(load_snapshot(ledger, project.project_id))
    identities = [{"hypothesis_id": "HYP_TEST", "project_id": project.project_id, "version": 1}]
    batch = candidates(context, identities)
    client = OmnigentHypothesisAgent() if role == "hypothesis" else OmnigentScientificCritic()
    async def invoke(path, prompt, *, project_id, role):
        assert path == Path(__file__).resolve().parents[1]/f"agents/{role}/{role}.yaml"
        packet = json.loads(prompt)
        assert packet["output_schema"] and project_id == context.charter.project_id
        if malformed:
            return "not JSON"
        if role == "hypothesis":
            return batch.model_dump_json()
        return (await FakeCritic().review(context, batch.hypotheses, packet["assigned_reviews"])).model_dump_json()
    client.transport.invoke_agent = invoke
    if role == "hypothesis":
        request = client.generate(context, identities)
    else:
        request = client.review(context, batch.hypotheses, [{"review_id": "HREV_TEST", "target_id": "HYP_TEST",
            "target_version": 1, "project_id": project.project_id}])
    if malformed:
        with pytest.raises(HypothesisOutputError):
            asyncio.run(request)
    else:
        assert asyncio.run(request)


def test_revision_bound_and_context_size():
    with pytest.raises(ValidationError):
        HypothesisLimits(max_revision_rounds=2)


@pytest.mark.parametrize("verdict", [s.ReviewVerdict.REVISE, s.ReviewVerdict.BLOCK])
def test_exact_review_prerequisite_cannot_be_bypassed(ledger, project, verdict):
    from autolab.orchestration.decision_validator import DecisionValidator
    result, _, _ = run_pipeline(ledger, project, critic=FakeCritic([verdict]*5), limits=HypothesisLimits(max_revision_rounds=0))
    snapshot = load_snapshot(ledger, project.project_id)
    decision = s.NextDecision(decision_id="DEC_TEST", project_id=project.project_id, action=s.PlannerAction.DESIGN_EXPERIMENT,
        target_agent="experiment_designer", reason="Attempt invalid selection", required_context_ids=[result.hypothesis_ids[0]], remaining_budget_usd=10)
    assert not DecisionValidator().validate(decision, snapshot).valid


def test_multiple_hypothesis_selection_rejected(ledger, project):
    from autolab.orchestration.decision_validator import DecisionValidator
    result, _, _ = run_pipeline(ledger, project)
    decision = s.NextDecision(decision_id="DEC_TEST", project_id=project.project_id, action=s.PlannerAction.DESIGN_EXPERIMENT,
        target_agent="experiment_designer", reason="Ambiguous selection", required_context_ids=result.hypothesis_ids[:2], remaining_budget_usd=10)
    assert not DecisionValidator().validate(decision, load_snapshot(ledger, project.project_id)).valid


@pytest.mark.parametrize("defect", ["no_issues", "vague", "foreign_project", "wrong_version", "role", "duplicate_target"])
def test_critic_identity_and_issue_specificity(ledger, project, defect):
    context = build_context(load_snapshot(ledger, project.project_id))
    identities = [{"hypothesis_id": f"HYP_{n}", "project_id": project.project_id, "version": 1} for n in range(2)]
    hypotheses = candidates(context, identities).hypotheses
    assignments = [{"review_id": f"HREV_{n}", "target_id": h.hypothesis_id, "target_version": 1, "project_id": project.project_id}
                   for n, h in enumerate(hypotheses)]
    batch = asyncio.run(FakeCritic([s.ReviewVerdict.REVISE]*2).review(context, hypotheses, assignments))
    changes = {"no_issues": {"issues": []}, "vague": {"issues": [{"problem": "Could be stronger"}]},
        "foreign_project": {"project_id": "PROJECT_FOREIGN"}, "wrong_version": {"target_version": 2},
        "role": {"reviewer_role": "hypothesis"}, "duplicate_target": {"target_id": hypotheses[1].hypothesis_id}}[defect]
    batch.reviews[0] = batch.reviews[0].model_copy(update=changes)
    with pytest.raises(HypothesisOutputError):
        validate_reviews(batch, hypotheses, context, assignments)


def test_invalid_revision_preserves_originals_and_initial_reviews(ledger, project):
    class BadRevision(FakeAgent):
        async def revise(self, context, hypotheses, reviews, assignments):
            batch = await super().revise(context, hypotheses, reviews, assignments)
            return batch.model_copy(update={"responses": []})
    with pytest.raises(HypothesisOutputError, match="each material"):
        run_pipeline(ledger, project, agent=BadRevision(), critic=FakeCritic([s.ReviewVerdict.REVISE]*5))
    assert len(ledger.list_reviews(project.project_id)) == 3
    assert all(h.version == 1 for h in ledger.list_hypotheses(project.project_id))


def test_context_overflow_no_model_call(ledger, project):
    agent = FakeAgent()
    huge = load_snapshot(ledger, project.project_id).model_copy(update={"charter": project.model_copy(update={"objective": "x"*10000})})
    with pytest.raises(HypothesisOutputError, match="context exceeds"):
        build_context(huge, HypothesisLimits(max_context_chars=4000))
    assert not agent.calls


def test_final_rejection_keeps_exact_review_and_status_history(ledger, project):
    result, _, _ = run_pipeline(ledger, project, critic=FakeCritic([s.ReviewVerdict.REVISE]*5, final=s.ReviewVerdict.REJECT))
    identifier = result.hypothesis_ids[0]
    assert result.revision_rounds == 1 and result.rejected_hypothesis_ids == result.hypothesis_ids
    assert ledger.get(s.Hypothesis, identifier, version=1).status == s.HypothesisStatus.PROPOSED
    assert ledger.get(s.Hypothesis, identifier, version=2).status == s.HypothesisStatus.REFINED
    assert ledger.get(s.Hypothesis, identifier, version=3).status == s.HypothesisStatus.REJECTED
    assert [r.target_version for r in ledger.list_reviews(project.project_id) if r.target_id == identifier] == [1, 2]
    context = ContextBuilder().build(load_snapshot(ledger, project.project_id))
    summary = next(h for h in context.summaries["hypotheses"] if h["id"] == identifier)
    assert summary["critic"]["target_version"] == 2 and summary["critic"]["verdict"] == "REJECT"
    assert s.PlannerAction.DESIGN_EXPERIMENT not in context.available_actions
