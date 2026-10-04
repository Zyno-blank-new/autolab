"""Paid adaptive Planner check, or a separate selection-ready fixture check."""
import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from autolab import schemas as s
from autolab.config import PROJECT_ROOT, configure
from autolab.ledger import ResearchLedger
from autolab.evidence_integration_smoke import ObservedPlanner
from autolab.experiment_design_smoke_helpers import seed_design
from autolab.experiment_selection_smoke_helpers import (
    seed_selection_ready, selection_outcome, verify_planner_outcome,
)
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_experiment
from autolab.planner.service import runtime_metadata


async def smoke(*, selection_ready=False):
    configure()
    with TemporaryDirectory(prefix="autolab-experiment-selection-") as directory:
        path = Path(directory) / "selection.db"
        with ResearchLedger(path) as ledger:
            if selection_ready:
                project, provenance = seed_selection_ready(ledger)
            else:
                project, _ = seed_design(ledger)
                provenance = {"source_checkpoint": "results/phase6-experiment-design-smoke.json",
                              "scope": "Original adaptive literature-assessment project"}
            before = load_snapshot(ledger, project.project_id)
            planner = ObservedPlanner()
            route = await Orchestrator(ledger, planner).decide(project.project_id)
            snapshot = verify_planner_outcome(ledger, before, route)
            context = planner.contexts[-1]
            assert {c.candidate_id for c in before.candidates} <= {
                c["id"] for c in context.summaries["candidates"]}
            decision = ledger.get(s.NextDecision, route.decision_id)
            experiment = selected_experiment(snapshot)
            selection = next((e for e in reversed(snapshot.events) if e.event_type == "EXPERIMENT_SELECTED"
                              and e.payload.get("decision_id") == route.decision_id), None)
            status = selection_outcome(route, selection_ready=selection_ready)
            report = {"status": status, "mode": "selection_ready" if selection_ready else "adaptive",
                "scientifically_legal": True, "decision_persisted": True, "event_persisted": True,
                "selected_candidate_id": selection.payload["candidate_id"] if selection else None,
                "experiment_spec_created": experiment.experiment_id if experiment else None,
                "boundary": route.control_state.value, "experiment_executed": False,
                "planner_decision": decision.model_dump(mode="json"),
                "planner_context": context.model_dump(mode="json"),
                "model_metadata": runtime_metadata(planner), "model_calls": {"planner": planner.calls},
                "fixture_provenance": provenance, "snapshot": snapshot.model_dump(mode="json")}
        with ResearchLedger(path) as reopened:
            assert verify_planner_outcome(reopened, before, route) == snapshot
        name = "phase6-selection-ready-smoke.json" if selection_ready else "phase6-adaptive-planner-smoke.json"
        output = PROJECT_ROOT / "results" / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print("AUTOLAB_SELECTION_READY_" + status if selection_ready else "AUTOLAB_PLANNER_ADAPTIVITY_OK")
        print(f"Planner action: {route.action.value} → {route.target_role}")
        print(f"Reason: {route.reason}")
        print("Legal decision and event persisted: yes")
        print(f"Selected candidate: {report['selected_candidate_id'] or 'none'}")
        print(f"ExperimentSpec: {report['experiment_spec_created'] or 'none'}")
        print("Resources prepared: no; experiment code generated: no; experiment executed: no")
        print(f"Control boundary: {route.control_state.value}; no Phase 7 component executed")
        print(f"Planner model calls: {planner.calls}")
        print(f"Scientific output: {output}")
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-ready", action="store_true",
                        help="Use the separate empirical-protocol fixture; report legal divergence honestly")
    asyncio.run(smoke(selection_ready=parser.parse_args().selection_ready))
