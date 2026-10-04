"""Phase 7 isolated fixtures: canonical science, no resource acquisition."""
import asyncio
import json
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.experiment_selection_smoke_helpers import seed_selection_ready, verify_no_execution
from autolab.feasibility.capability_registry import CapabilityRegistry
from autolab.feasibility.models import Capability, CostInput, EstimateRange, FeasibilityInputs, ResourceAccess
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_experiment


def seed_selected(ledger):
    path = PROJECT_ROOT / "results/phase6-selection-ready-smoke.json"
    if path.exists():
        snapshot = json.loads(path.read_text())["snapshot"]
        project = ledger.create_project(s.ResearchCharter.model_validate({**snapshot["charter"], "created_at": s.utc_now()}))
        for model, name in ((s.SourceRecord,"sources"),(s.EvidenceRecord,"evidence"),(s.Hypothesis,"hypotheses"),
            (s.ExperimentCandidate,"candidates"),(s.ExperimentSpec,"experiments"),(s.ReviewRecord,"reviews"),
            (s.NextDecision,"decisions"),(s.EventRecord,"events")):
            ledger.add_many([model.model_validate(row) for row in snapshot[name]])
        provenance = "Saved real GPT-6.1 Sol selected ExperimentSpec; fresh isolated charter clock"
    else:
        project,_ = seed_selection_ready(ledger)
        # Clean-checkout alternative: explicitly controlled fixture selection,
        # not presented as a real Planner call or a new scientific result.
        class FixturePlanner:
            async def propose(self, context, decision_id, feedback=None):
                candidate = context.summaries["candidates"][0]
                return s.NextDecision(decision_id=decision_id,project_id=project.project_id,
                    action="SELECT_EXPERIMENT",target_agent="planner",reason="Controlled offline Phase 7 seed selection",
                    required_context_ids=[candidate["id"]],remaining_budget_usd=project.budget_usd).model_dump_json()
        asyncio.run(Orchestrator(ledger, FixturePlanner()).decide(project.project_id))
        provenance = "Controlled offline seed from committed real scientific proposal fixture; no Planner API call"
    snapshot = load_snapshot(ledger, project.project_id)
    experiment = selected_experiment(snapshot)
    assert experiment and len(snapshot.experiments)==1
    verify_no_execution(snapshot)
    assert not any(e.event_type=="HUMAN_APPROVED" for e in snapshot.events)
    return project,experiment,provenance


def explicit_test_planning(experiment):
    """Simulated planning declarations, never actual availability or API prices."""
    registry = CapabilityRegistry([Capability(capability_id=r,status="AVAILABLE",provider="explicit isolated test declaration")
        for r in experiment.required_capabilities])
    inputs = FeasibilityInputs(resource_access=[ResourceAccess(requirement=r,status="AVAILABLE",
        notes=["Test-only planning access assumption; no resource acquired, prepared or audited."])
        for r in experiment.required_resources],
        costs=[CostInput(category="test-configured total pursuit cost",unit_price_usd=1,
            units=EstimateRange(minimum=1,expected=2,maximum=3),unit="illustrative test budget unit",confidence=0.3,
            assumptions=["Isolated test configuration: $1–$3 total pursuit envelope, not current provider pricing or measured spend."])],
        runtime_minutes=EstimateRange(minimum=15,expected=20,maximum=30),
        runtime_assumptions=["Test-only total preparation, implementation, validation and execution duration range; not measured."],
        compute_requirements=["Test declaration of a suitable local execution environment; no compute provisioned"],
        implementation_complexity="HIGH",
        execution_risks=["Fault/scoring validity, sample adequacy and independent readiness must be validated before any run."],
        warnings=["Capability/resource declarations are simulated test facts, not a production readiness audit.",
                  "Approval scope is preparation only; no implementation or run is authorized."])
    return registry,inputs


def save_report(name, ledger, project_id, **extra):
    snapshot=load_snapshot(ledger,project_id)
    verify_no_execution(snapshot)
    output=PROJECT_ROOT / "results" / name
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({"snapshot":snapshot.model_dump(mode="json"),**extra},indent=2,allow_nan=False)+"\n")
    return output,snapshot
