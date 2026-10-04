"""Control-plane tests use only fixtures and fake Planners; no API calls."""
import asyncio
import json
import sqlite3
from pathlib import Path
from datetime import timedelta

import pytest
from pydantic import ValidationError

from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.orchestration.budget import calculate_budget, calculate_time
from autolab.orchestration.context_builder import ContextBuilder, ContextTooLargeError
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.models import ContextLimits, ControlStage as C, ProjectSnapshot, ValidationStatus as V
from autolab.orchestration.orchestrator import IllegalDecisionError, Orchestrator
from autolab.orchestration.role_registry import Role, RoleRegistry
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import (charter_fingerprint, derive_control_state, selected_experiment,
                                               readiness_passes, approval_for)
from autolab.planner import PlannerInvocationError, PlannerOutputError
from autolab.planner.prompt import planner_request
from autolab.feasibility.capability_registry import CapabilityRegistry
from autolab.feasibility.models import Capability, CostInput, EstimateRange, FeasibilityInputs
from autolab.feasibility.persistence import assessment_fingerprint, spec_fingerprint
from autolab.feasibility.service import FeasibilityService

A = s.PlannerAction


@pytest.fixture
def initial(ledger):
    ledger.create_project(s.ResearchCharter(project_id="PROJECT_0001", title="AI research",
        research_question="Which method improves reliability?", objective="Measure improvement",
        primary_outcome="Success", budget_usd=10, max_runtime_minutes=60))
    return load_snapshot(ledger, "PROJECT_0001")


@pytest.fixture
def ready(ledger, records, tmp_path):
    snapshot = load_snapshot(ledger, records[s.ResearchCharter].project_id)
    h, e, i, a = records[s.Hypothesis], records[s.ExperimentSpec], records[s.ImplementationRecord], records[s.ScientificAnalysis]
    reviews = [s.ReviewRecord(review_id=f"HREV_PASS_{n}", project_id=e.project_id, review_type=kind,
        target_type=model.__name__, target_id=identifier, verdict="PASS", reviewer_role="fixture auditor")
        for n, (kind, model, identifier) in enumerate((
            ("hypothesis", s.Hypothesis, h.hypothesis_id), ("experiment", s.ExperimentSpec, e.experiment_id),
            ("code", s.ImplementationRecord, i.implementation_id), ("analysis", s.ScientificAnalysis, a.analysis_id)))]
    # Phase 7 strengthens the same gate: old successful-path fixtures now carry
    # an explicit assessment rather than bypassing execution feasibility.
    ledger.add_many(reviews)
    assessment = FeasibilityService(ledger, CapabilityRegistry([
        Capability(capability_id=name, status="AVAILABLE") for name in e.required_capabilities])).assess(
        e.project_id, e.experiment_id, FeasibilityInputs(
            costs=[CostInput(category="explicit offline fixture", unit_price_usd=e.estimated_cost_usd,
                units=EstimateRange(minimum=1, expected=1, maximum=1), assumptions=["Synthetic test configuration"])],
            runtime_minutes=EstimateRange(minimum=0, expected=0, maximum=0),
            compute_requirements=["Fixture CPU"], storage_gb=EstimateRange(maximum=0)))
    snapshot = load_snapshot(ledger, e.project_id)
    approval = s.EventRecord(event_id="EVENT_APPROVAL", project_id=e.project_id, event_type="HUMAN_APPROVED", actor="human",
        summary="Scoped fixture approval", payload={"experiment_id": e.experiment_id, "experiment_version": e.version,
          "approved_actions": [A.PREPARE_RESOURCES.value, A.IMPLEMENT_EXPERIMENT.value, A.RUN_EXPERIMENT.value],
          "max_cost_usd": 25, "max_runtime_minutes": 60, "implementation_id": i.implementation_id,
          "assessment_id": assessment.assessment_id, "assessment_version": assessment.version,
          "assessment_fingerprint": assessment_fingerprint(assessment), "spec_fingerprint": spec_fingerprint(e)})
    test = s.EventRecord(event_id="EVENT_TEST", project_id=e.project_id, event_type="IMPLEMENTATION_TESTED",
        actor="experiment_runner", summary="Deterministic fixture tests", payload={"implementation_id": i.implementation_id, "status": "PASS"})
    report = records[s.ReadinessReport].model_copy(update={"verdict": s.ReadinessVerdict.PASS,
        "resource_readiness": True, "technical_readiness": True, "scientific_readiness": True,
        "quality_readiness": True, "failed_checks": []})
    # Phase 8 successful-path fixtures now contain actual immutable data and
    # exact manifest pins instead of treating a bare legacy PASS as readiness.
    from autolab.preparation.models import AcceptanceCriteria, ResourceRequirement, ResourcePreparationPlan, ResourceManifest, ResourcePin
    from autolab.preparation.manifest import checksum, fingerprint
    data_path = tmp_path / "control-fixture.json"
    data_path.write_text('{"fixture": "bounded configuration"}')
    acceptance = AcceptanceCriteria(scientific=["Offline control fixture"], technical=["Readable JSON"], provenance=["Exact checksum"])
    requirement = ResourceRequirement(requirement_id="fixture", spec_requirements=["Offline fixture configuration"],
        resource_type="configuration", purpose="Control-plane test input", acquisition_mode="EXISTING",
        expected_output="JSON configuration", required_capabilities=["filesystem_access"], steps=["Reference fixture"],
        criteria=acceptance, handler="local", parameters={"path": str(data_path)})
    plan = ResourcePreparationPlan(plan_id="PPLAN_FIXTURE", project_id=e.project_id, experiment_id=e.experiment_id,
        experiment_version=e.version, spec_fingerprint=spec_fingerprint(e), resource_requirements=[requirement])
    resource = records[s.ResourceRecord].model_copy(update={"path_or_uri": str(data_path), "checksum": checksum(data_path),
        "status": "PREPARED", "metadata": {"logical_resource_id": records[s.ResourceRecord].resource_id}})
    manifest = ResourceManifest(manifest_id="MANIFEST_FIXTURE", project_id=e.project_id, experiment_id=e.experiment_id,
        experiment_version=e.version, plan_id=plan.plan_id, plan_version=1, spec_fingerprint=spec_fingerprint(e),
        resources=[ResourcePin(requirement_id="fixture", resource_id=resource.resource_id, version=resource.version,
            checksum=resource.checksum, path=resource.path_or_uri, record_fingerprint=fingerprint(resource), status=resource.status)],
        validation_requirements={"fixture": acceptance}, manifest_path=str(tmp_path / "fixture-manifest.json"))
    Path(manifest.manifest_path).write_text(manifest.model_dump_json())
    plan_event = s.EventRecord(event_id="EVENT_PLAN_FIXTURE", project_id=e.project_id, event_type="PREPARATION_PLAN_CREATED",
        actor="preparation", target_type="experiments", target_id=e.experiment_id, summary="Explicit offline preparation contract",
        payload={"experiment_version": e.version, "plan": plan.model_dump(mode="json")})
    manifest_event = s.EventRecord(event_id="EVENT_MANIFEST_FIXTURE", project_id=e.project_id, event_type="RESOURCE_MANIFEST_CREATED",
        actor="preparation", target_type="experiments", target_id=e.experiment_id, summary="Explicit offline immutable manifest",
        payload={"experiment_version": e.version, "manifest": manifest.model_dump(mode="json")})
    report = report.model_copy(update={"metadata": {"auditor_role": "readiness", "manifest_id": manifest.manifest_id,
        "manifest_fingerprint": fingerprint(manifest), "spec_fingerprint": manifest.spec_fingerprint,
        "resource_pins": [pin.model_dump(mode="json") for pin in manifest.resources]}})
    readiness_event = s.EventRecord(event_id="EVENT_READY_FIXTURE", project_id=e.project_id,
        event_type="READINESS_PASSED", actor="readiness", target_type="readiness_reports", target_id=report.readiness_id,
        summary="Explicit independent offline audit", payload={"manifest_id": manifest.manifest_id})
    snapshot = snapshot.model_copy(update={"reviews": reviews, "readiness": [report], "resources": [resource],
        "implementations": [i.model_copy(update={"status": "APPROVED"})], "events": [*snapshot.events, plan_event, manifest_event, readiness_event, approval, test], "runs": [], "analyses": []})
    # Phase 9 strengthens the gate again: bare status/test strings are no longer
    # authorization. Preserve the original control cases with explicit exact pins.
    from phase9_control_fixture import pin_control_fixture
    return pin_control_fixture(snapshot, tmp_path)


def proposal(snapshot, action=A.GATHER_EVIDENCE, target="evidence", **changes):
    return s.NextDecision.model_validate(dict(decision_id="DEC_TEST", project_id=snapshot.charter.project_id,
        action=action, target_agent=target, reason="Choose a scientifically informative action.",
        remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd, **changes))


def with_event(snapshot, kind, actor="human", **payload):
    event = s.EventRecord(event_id="EVENT_CONTROL", project_id=snapshot.charter.project_id,
        event_type=kind, actor=actor, summary="Fixture control event", payload=payload)
    return snapshot.model_copy(update={"events": [*snapshot.events, event]})


def test_initial_state(initial):
    assert derive_control_state(initial) == C.INITIALIZED


def test_evidence_and_hypothesis_states(ready):
    snapshot = ready.model_copy(update={"experiments": [], "events": [], "hypotheses": []})
    assert derive_control_state(snapshot) == C.HYPOTHESIS_FORMATION
    snapshot = snapshot.model_copy(update={"hypotheses": ready.hypotheses})
    assert derive_control_state(snapshot) == C.HYPOTHESIS_REVIEW
    snapshot = with_event(snapshot, "HYPOTHESIS_SELECTED", hypothesis_id=ready.hypotheses[0].hypothesis_id, version=1)
    assert derive_control_state(snapshot) == C.EXPERIMENT_DESIGN


def test_approval_resource_and_implementation_states(ready):
    no_approval = ready.model_copy(update={"events": [], "resources": [], "readiness": [], "implementations": []})
    assert derive_control_state(no_approval) == C.AWAITING_HUMAN_APPROVAL
    prepared = ready.model_copy(update={"readiness": [], "implementations": []})
    assert derive_control_state(prepared) == C.READINESS_REVIEW
    assert derive_control_state(ready.model_copy(update={"implementations": []})) == C.IMPLEMENTATION
    assert derive_control_state(ready) == C.READY_TO_RUN
    assert derive_control_state(ready.model_copy(update={"reviews": [r for r in ready.reviews if r.review_type != "code"]})) == C.CODE_REVIEW


def test_analysis_and_adaptive_states(ready, records):
    run = records[s.ExperimentRun]
    from phase10_control_fixture import pin_result_fixture
    snapshot = pin_result_fixture(ready, run)
    assert derive_control_state(snapshot) == C.ANALYSIS
    from phase11_control_fixture import pin_analysis_fixture
    snapshot = pin_analysis_fixture(snapshot, records[s.ScientificAnalysis])
    assert derive_control_state(snapshot) == C.ADAPTIVE_DECISION
    assert derive_control_state(snapshot.model_copy(update={"reviews": [r for r in snapshot.reviews if r.review_type != "analysis"]})) == C.ANALYSIS_REVIEW
    assert derive_control_state(snapshot.model_copy(update={"runs": [run.model_copy(update={"status": s.RunStatus.RUNNING})]})) == C.RUNNING


def test_legal_and_illegal_initial_actions(initial):
    validator = DecisionValidator()
    assert validator.validate(proposal(initial), initial).valid
    for action, target in ((A.RUN_EXPERIMENT, "experiment_runner"), (A.ANALYZE_RESULT, "analyst"),
                           (A.IMPLEMENT_EXPERIMENT, "implementer"), (A.GENERATE_HYPOTHESES, "hypothesis")):
        assert not validator.validate(proposal(initial, action, target), initial).valid


@pytest.mark.parametrize("field", ["resources", "technical", "scientific", "quality"])
def test_readiness_requires_all_four_gates(ready, field):
    name = {"resources": "resource_readiness", "technical": "technical_readiness",
            "scientific": "scientific_readiness", "quality": "quality_readiness"}[field]
    snapshot = ready.model_copy(update={"readiness": [ready.readiness[0].model_copy(update={name: False})]})
    assert not readiness_passes(snapshot)
    assert not DecisionValidator().validate(proposal(snapshot, A.IMPLEMENT_EXPERIMENT, "implementer"), snapshot).valid


def test_new_resource_invalidates_previous_readiness(ready):
    report = ready.readiness[0]
    resource = ready.resources[0].model_copy(update={"created_at": report.created_at+timedelta(seconds=1)})
    assert not readiness_passes(ready.model_copy(update={"resources": [resource]}))


@pytest.mark.parametrize("missing", ["readiness", "implementations", "code_review", "tests", "approval"])
def test_run_requires_all_gates(ready, missing):
    updates = {}
    if missing in ("readiness", "implementations"):
        updates[missing] = []
    elif missing == "code_review":
        updates["reviews"] = [r for r in ready.reviews if r.review_type != "code"]
    else:
        kind = "IMPLEMENTATION_TESTED" if missing == "tests" else "HUMAN_APPROVED"
        updates["events"] = [e for e in ready.events if e.event_type != kind]
    snapshot = ready.model_copy(update=updates)
    assert not DecisionValidator().validate(proposal(snapshot, A.RUN_EXPERIMENT, "experiment_runner"), snapshot).valid
    assert DecisionValidator().validate(proposal(ready, A.RUN_EXPERIMENT, "experiment_runner"), ready).valid


def test_approval_must_be_human_and_scoped(ready):
    for changes in ({"actor": "planner"}, {"payload": {"experiment_id": "EXP_OTHER"}},
                    {"payload": {**ready.events[-2].payload, "experiment_version": 2}},
                    {"payload": {**ready.events[-2].payload, "implementation_id": "IMPL_OTHER"}}):
        events = [e.model_copy(update=changes) if e.event_type == "HUMAN_APPROVED" else e for e in ready.events]
        snapshot = ready.model_copy(update={"events": events})
        assert approval_for(snapshot, A.RUN_EXPERIMENT) is None


def test_latest_rejection_revokes_approval(ready):
    e = ready.experiments[0]
    snapshot = with_event(ready, "HUMAN_REJECTED", experiment_id=e.experiment_id, experiment_version=e.version)
    assert approval_for(snapshot, A.PREPARE_RESOURCES) is None
    assert DecisionValidator().validate(proposal(snapshot, A.PREPARE_RESOURCES, "preparation"), snapshot).status == V.NEEDS_HUMAN_APPROVAL


def test_version_selection_is_pinned(ready):
    old = selected_experiment(ready)
    new = old.model_copy(update={"version": 2})
    snapshot = ready.model_copy(update={"experiments": [old, new]})
    assert selected_experiment(snapshot).version == 1


def test_analysis_requires_completed_run(ready, records):
    validator = DecisionValidator()
    assert not validator.validate(proposal(ready, A.ANALYZE_RESULT, "analyst"), ready).valid
    run = records[s.ExperimentRun]
    for change in ({"status": s.RunStatus.RUNNING}, {"completed_at": None}):
        snapshot = ready.model_copy(update={"runs": [run.model_copy(update=change)]})
        assert not validator.validate(proposal(snapshot, A.ANALYZE_RESULT, "analyst"), snapshot).valid
    snapshot = ready.model_copy(update={"runs": [run]})
    # A legacy COMPLETED label without raw/metric integrity is no longer enough.
    assert not validator.validate(proposal(snapshot, A.ANALYZE_RESULT, "analyst"), snapshot).valid
    from phase10_control_fixture import pin_result_fixture
    snapshot = pin_result_fixture(ready, run)
    assert validator.validate(proposal(snapshot, A.ANALYZE_RESULT, "analyst"), snapshot).valid


@pytest.mark.parametrize("target", ["nonexistent", "implementer", None])
def test_role_validation(initial, target):
    assert DecisionValidator().validate(proposal(initial, target=target), initial).status == V.INVALID


def test_action_enum_validation(initial):
    data = proposal(initial).model_dump()
    data["action"] = "MAKE_STUFF_UP"
    assert DecisionValidator().validate(data, initial).status == V.INVALID


def test_control_overlays_do_not_mutate_charter(initial):
    paused = with_event(initial, "PROJECT_PAUSED")
    assert derive_control_state(paused) == C.PAUSED
    assert not DecisionValidator().validate(proposal(paused), paused).valid
    assert derive_control_state(with_event(paused, "PROJECT_UNBLOCKED")) == C.PAUSED
    resumed = with_event(paused, "PROJECT_RESUMED")
    assert derive_control_state(resumed) == C.INITIALIZED
    assert initial.charter == resumed.charter


@pytest.mark.parametrize("status", [s.ProjectStatus.PAUSED, s.ProjectStatus.COMPLETED, s.ProjectStatus.STOPPED])
def test_stop_is_always_legal(initial, status):
    snapshot = initial.model_copy(update={"charter": initial.charter.model_copy(update={"status": status})})
    stop = s.NextDecision(decision_id="DEC_STOP", project_id=snapshot.charter.project_id, action=A.STOP, reason="Stop now")
    assert DecisionValidator().validate(stop, snapshot).valid
    assert not DecisionValidator().validate(proposal(snapshot), snapshot).valid


def test_blocked_allows_replanning_but_not_execution(ready):
    snapshot = with_event(ready, "PROJECT_BLOCKED", actor="orchestrator")
    assert derive_control_state(snapshot) == C.BLOCKED
    validator = DecisionValidator()
    assert validator.validate(proposal(snapshot), snapshot).valid
    assert validator.validate(proposal(snapshot, A.DESIGN_EXPERIMENT, "experiment_designer"), snapshot).valid
    assert not validator.validate(proposal(snapshot, A.RUN_EXPERIMENT, "experiment_runner"), snapshot).valid


def test_budget_uses_known_actual_not_estimates(initial):
    project = initial.charter.project_id
    costs = [s.CostRecord(cost_id="COST_1", project_id=project, category="compute", estimated_usd=8, actual_usd=2),
             s.CostRecord(cost_id="COST_2", project_id=project, category="future", estimated_usd=20)]
    budget = calculate_budget(initial.model_copy(update={"costs": costs}))
    assert budget.actual_spent_usd == 2 and budget.estimated_spent_usd == 28 and budget.remaining_budget_usd == 8
    assert budget.unknown_actual_cost_ids == ["COST_2"]
    assert calculate_budget(initial).actual_spent_usd == 0


def test_unpriced_zero_placeholder_is_unknown_actual_spend(initial):
    costs = [s.CostRecord(cost_id="COST_UNKNOWN", project_id=initial.charter.project_id,
        category="Unpriced model calls", metadata={"actual_known": False, "estimate_only": True}),
        s.CostRecord(cost_id="COST_MEASURED_FREE", project_id=initial.charter.project_id,
        category="Measured free execution", metadata={"actual_known": True})]
    budget = calculate_budget(initial.model_copy(update={"costs": costs}))
    assert budget.unknown_actual_cost_ids == ["COST_UNKNOWN"]
    assert budget.actual_spent_usd == 0
    assert budget.remaining_budget_usd == initial.charter.budget_usd


def test_known_over_budget_blocked(ready):
    # Consume actual budget without silently mutating the approved contract.
    # Its known assessed cost now exceeds the remaining amount.
    expense = s.CostRecord(cost_id="COST_LATER", project_id=ready.charter.project_id,
        category="known additional spend", actual_usd=24.5)
    snapshot = ready.model_copy(update={"costs": [*ready.costs, expense]})
    assert DecisionValidator().validate(proposal(snapshot, A.PREPARE_RESOURCES, "preparation"), snapshot).status == V.BUDGET_BLOCKED


def test_budget_amount_not_model_invented(initial):
    data = proposal(initial).model_dump()
    data["remaining_budget_usd"] = 1000
    assert DecisionValidator().validate(data, initial).status == V.INVALID


def test_time_awareness_and_expiration(initial):
    now = initial.charter.created_at+timedelta(minutes=5)
    time = calculate_time(initial, now)
    assert time.elapsed_minutes == 5 and time.remaining_minutes == 55
    no_limit = initial.model_copy(update={"charter": initial.charter.model_copy(update={"max_runtime_minutes": 0})})
    assert calculate_time(no_limit, now).remaining_minutes is None
    expired = initial.charter.created_at+timedelta(minutes=61)
    assert DecisionValidator().validate(proposal(initial), initial, now=expired).status == V.TIME_BLOCKED
    assert DecisionValidator().validate(proposal(initial, A.STOP, None), initial, now=expired).valid


def test_context_is_compact_and_keeps_current_records(ready):
    huge = "PRIVATE_FULL_PAPER"*10000
    sources = [ready.sources[0].model_copy(update={"abstract": huge})]
    events = [s.EventRecord(event_id=f"EVENT_LARGE_{n}", project_id=ready.charter.project_id, event_type="NOTE", actor="fixture",
        summary="Short event", payload={"logs": huge}) for n in range(100)]
    snapshot = ready.model_copy(update={"sources": sources, "events": [*ready.events, *events]})
    context = ContextBuilder(ContextLimits(recent_events=3)).build(snapshot)
    assert len(context.summaries["events"]) == 3
    assert context.omitted_records["events"] >= 100
    assert huge not in context.model_dump_json() and "PRIVATE_FULL_PAPER" not in context.model_dump_json()
    assert context.current_records["experiment"]["id"] == ready.experiments[0].experiment_id
    assert context.current_records["implementation"]["id"] == ready.implementations[0].implementation_id
    assert context.charter == ready.charter
    assert len(context.model_dump_json()) < 24000


def test_context_hard_size_limit(initial):
    large = initial.model_copy(update={"charter": initial.charter.model_copy(update={"constraints": {"huge": "x"*30000}})})
    with pytest.raises(ContextTooLargeError):
        ContextBuilder().build(large)


def test_invalid_charter_mutation_and_foreign_ids(initial):
    data = proposal(initial).model_dump()
    data["research_question"] = "Different objective"
    assert DecisionValidator().validate(data, initial).status == V.INVALID
    assert not DecisionValidator().validate(proposal(initial, required_context_ids=["EVID_FOREIGN"]), initial).valid
    data = proposal(initial).model_dump()
    data["project_id"] = "PROJECT_OTHER"
    assert not DecisionValidator().validate(data, initial).valid
    assert not DecisionValidator().validate(proposal(initial), initial, expected_charter_fingerprint="wrong").valid


class FakePlanner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0
        self.contexts = []
        self.feedback = []
    async def propose(self, context, decision_id, feedback=None):
        self.contexts.append(context)
        self.feedback.append(feedback)
        value = self.responses[min(self.calls, len(self.responses)-1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        if value == "malformed":
            return "not JSON"
        action, target = value
        return s.NextDecision(decision_id=decision_id, project_id=context.charter.project_id,
            action=action, target_agent=target, reason="Fixture scientific decision",
            remaining_budget_usd=context.budget.remaining_budget_usd).model_dump_json()


def test_decision_and_event_persist_and_route(ledger, initial):
    fake = FakePlanner([(A.GATHER_EVIDENCE, "evidence")])
    route = asyncio.run(Orchestrator(ledger, fake).decide(initial.charter.project_id))
    assert route.target_role == "evidence" and fake.calls == 1
    decisions = ledger.list_decisions(initial.charter.project_id)
    events = ledger.list_events(initial.charter.project_id)
    assert len(decisions) == len(events) == 1
    assert events[0].actor == "planner" and events[0].event_type == "PLANNER_DECISION"
    assert events[0].payload["decision_id"] == decisions[0].decision_id == route.decision_id
    assert events[0].payload["target_role"] == "evidence"
    assert derive_control_state(load_snapshot(ledger, initial.charter.project_id)) == C.EVIDENCE_GATHERING
    assert ledger.get_project(initial.charter.project_id) == initial.charter


@pytest.mark.parametrize("first", ["malformed", (A.RUN_EXPERIMENT, "experiment_runner")])
def test_repair_once_then_success(ledger, initial, first):
    fake = FakePlanner([first, (A.GATHER_EVIDENCE, "evidence")])
    asyncio.run(Orchestrator(ledger, fake).decide(initial.charter.project_id))
    assert fake.calls == 2 and fake.contexts[0] == fake.contexts[1]
    assert fake.feedback[1]["attempts_remaining"] == 1
    assert len(ledger.list_decisions(initial.charter.project_id)) == 1


@pytest.mark.parametrize("responses,error", [(["malformed"], PlannerOutputError), ([(A.RUN_EXPERIMENT, "experiment_runner")], IllegalDecisionError)])
def test_repair_exhaustion_has_no_decision_or_route(ledger, initial, responses, error):
    fake = FakePlanner(responses)
    with pytest.raises(error):
        asyncio.run(Orchestrator(ledger, fake).decide(initial.charter.project_id))
    assert fake.calls == 2
    assert ledger.list_decisions(initial.charter.project_id) == []
    assert ledger.list_events(initial.charter.project_id) == []


def test_transport_failure_not_blindly_retried(ledger, initial):
    fake = FakePlanner([PlannerInvocationError("API unavailable")])
    with pytest.raises(PlannerInvocationError):
        asyncio.run(Orchestrator(ledger, fake).decide(initial.charter.project_id))
    assert fake.calls == 1


def test_pending_approval_is_first_class(ledger, initial):
    fake = FakePlanner([(A.REQUEST_HUMAN_APPROVAL, "human")])
    route = asyncio.run(Orchestrator(ledger, fake).decide(initial.charter.project_id))
    assert route.target_role == "human" and route.control_state == C.AWAITING_HUMAN_APPROVAL


def test_stop_persists_terminal_control_without_charter_mutation(ledger, initial):
    route = asyncio.run(Orchestrator(ledger, FakePlanner([(A.STOP, None)])).decide(initial.charter.project_id))
    assert route.control_state == C.COMPLETED
    assert ledger.get_project(initial.charter.project_id) == initial.charter


def test_atomic_decision_event_rollback(ledger, initial):
    decision = proposal(initial)
    invalid_event = s.EventRecord(event_id="EVENT_BAD", project_id="PROJECT_MISSING", event_type="PLANNER_DECISION", actor="planner", summary="Bad FK")
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_many([decision, invalid_event])
    assert ledger.list_decisions(initial.charter.project_id) == []


def test_fresh_state_recheck_prevents_stale_route(ledger, initial):
    class ChangingPlanner(FakePlanner):
        async def propose(self, context, decision_id, feedback=None):
            ledger.add_event(s.EventRecord(event_id="EVENT_PAUSE", project_id=initial.charter.project_id,
                event_type="PROJECT_PAUSED", actor="human", summary="Pause while planning"))
            return await super().propose(context, decision_id, feedback)
    with pytest.raises(IllegalDecisionError, match="state changed"):
        asyncio.run(Orchestrator(ledger, ChangingPlanner([(A.GATHER_EVIDENCE, "evidence")])).decide(initial.charter.project_id))
    assert ledger.list_decisions(initial.charter.project_id) == []


def test_adaptive_graph_supports_different_actions(initial, ready, records):
    validator = DecisionValidator()
    a = set(validator.legal_actions(initial))
    b_snapshot = ready.model_copy(update={"experiments": [], "events": [], "hypotheses": [ready.hypotheses[0].model_copy(update={"status": s.HypothesisStatus.ACCEPTED})]})
    b = set(validator.legal_actions(b_snapshot))
    from phase10_control_fixture import pin_result_fixture
    from phase11_control_fixture import pin_analysis_fixture
    c_snapshot = pin_analysis_fixture(pin_result_fixture(ready, records[s.ExperimentRun]), records[s.ScientificAnalysis])
    c = set(validator.legal_actions(c_snapshot))
    assert A.GATHER_EVIDENCE in a and A.DESIGN_EXPERIMENT not in a
    assert A.DESIGN_EXPERIMENT in b
    assert {A.RUN_FOLLOWUP, A.COLLECT_MORE_DATA, A.REFINE_HYPOTHESIS, A.STOP} <= c
    assert a != b and b != c


def test_role_registry_supports_extension(initial):
    roles = RoleRegistry()
    roles.register(Role("additional_evidence"), actions=(A.GATHER_EVIDENCE,))
    assert DecisionValidator(roles).validate(proposal(initial, target="additional_evidence"), initial).valid
    with pytest.raises(ValueError):
        roles.register(Role("evidence"))


def test_structured_prompt_uses_canonical_schema(initial):
    context = ContextBuilder().build(initial)
    payload = json.loads(planner_request(context, "DEC_RESERVED"))
    assert payload["assigned_identity"] == {"decision_id": "DEC_RESERVED", "project_id": initial.charter.project_id}
    assert payload["output_schema"]["properties"]["action"]
    assert payload["planner_context"]["control_state"] == "INITIALIZED"


def test_pending_request_revokes_old_scope_until_answered(ready):
    request = proposal(ready, A.REQUEST_HUMAN_APPROVAL, "human")
    later = proposal(ready).model_copy(update={"decision_id": "DEC_LATER"})
    snapshot = ready.model_copy(update={"decisions": [request, later]})
    assert derive_control_state(snapshot) == C.AWAITING_HUMAN_APPROVAL
    assert approval_for(snapshot, A.RUN_EXPERIMENT) is None
    assert DecisionValidator().validate(proposal(snapshot, A.RUN_EXPERIMENT, "experiment_runner"), snapshot).status == V.NEEDS_HUMAN_APPROVAL
    prior_approval = next(e for e in reversed(ready.events) if e.event_type == 'HUMAN_APPROVED')
    approved = prior_approval.model_copy(update={"event_id": "EVENT_NEW_APPROVAL", "created_at": s.utc_now(),
        "payload": {**prior_approval.payload, "decision_id": request.decision_id}})
    snapshot = snapshot.model_copy(update={"events": [*snapshot.events, approved]})
    assert approval_for(snapshot, A.RUN_EXPERIMENT) is not None


def test_blocked_cannot_collect_data_via_preparation(ready):
    snapshot = with_event(ready, "PROJECT_BLOCKED", actor="orchestrator")
    assert not DecisionValidator().validate(proposal(snapshot, A.COLLECT_MORE_DATA, "preparation"), snapshot).valid
    assert DecisionValidator().validate(proposal(snapshot, A.COLLECT_MORE_DATA, "evidence"), snapshot).valid


def test_changed_evidence_requires_new_context_even_when_action_still_legal(ledger, initial):
    class ChangingPlanner(FakePlanner):
        async def propose(self, context, decision_id, feedback=None):
            ledger.add_cost(s.CostRecord(cost_id="COST_NEW", project_id=initial.charter.project_id,
                category="Estimate", estimated_usd=1))
            return await super().propose(context, decision_id, feedback)
    with pytest.raises(IllegalDecisionError, match="rebuild Planner context"):
        asyncio.run(Orchestrator(ledger, ChangingPlanner([(A.GATHER_EVIDENCE, "evidence")])).decide(initial.charter.project_id))
    assert ledger.list_decisions(initial.charter.project_id) == []


@pytest.mark.parametrize("exit_code", [0, 1])
def test_actual_adapter_uses_omnigent_transport_and_redacts_errors(initial, monkeypatch, tmp_path, exit_code):
    from autolab.planner import service
    captured = []
    monkeypatch.setattr(service, "configure", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-private-credential")
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(tmp_path))
    cache = tmp_path / "artifacts/.cache/agent"
    cache.mkdir(parents=True)
    cached_config = cache / "planner.yaml"
    cached_config.write_text("api_key: test-private-credential\n")
    class Process:
        returncode = exit_code
        async def communicate(self):
            return (b'Omnigent session: http://localhost/session\n{"action":"STOP"}',
                    b"API failure test-private-credential sk-fake-secret")
    async def spawn(*args, **kwargs):
        captured.append(args)
        return Process()
    monkeypatch.setattr(service.asyncio, "create_subprocess_exec", spawn)
    planner = service.OmnigentPlanner()
    if exit_code:
        with pytest.raises(PlannerInvocationError) as error:
            asyncio.run(planner.propose(ContextBuilder().build(initial), "DEC_RESERVED"))
        assert "test-private-credential" not in str(error.value)
        assert "sk-fake-secret" not in str(error.value)
    else:
        output = asyncio.run(planner.propose(ContextBuilder().build(initial), "DEC_RESERVED"))
        assert json.loads(output) == {"action": "STOP"}
    assert captured[0][1:4] == ("-m", "autolab.launch", "run")
    assert "--no-log" in captured[0] and "local" in captured[0]
    assert json.loads(captured[0][captured[0].index("-p")+1])["assigned_identity"]["decision_id"] == "DEC_RESERVED"
    assert planner.calls == 1
    assert "test-private-credential" not in cached_config.read_text()


def test_cache_cleanup_preserves_source_and_env(tmp_path):
    from autolab.planner.service import scrub_cached_credentials
    private = tmp_path / ".env"
    source = tmp_path / "planner.yaml"
    private.write_text("PRIVATE=fixture-key")
    source.write_text("auth: fixture-key")
    assert scrub_cached_credentials(tmp_path, "fixture-key") == 0
    assert private.read_text() == "PRIVATE=fixture-key"
    assert source.read_text() == "auth: fixture-key"
