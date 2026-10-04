"""Explicit paid integration check; excluded from pytest. No specialist runs."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import derive_control_state
from autolab.planner import OmnigentPlanner
from autolab.schemas import ResearchCharter


async def smoke() -> None:
    configure()
    with TemporaryDirectory(prefix="autolab-planner-") as directory:
        path = Path(directory) / "planner.db"
        with ResearchLedger(path) as ledger:
            project = ledger.create_project(ResearchCharter(
                project_id=ledger.next_id("PROJECT"), title="Agent recovery reliability",
                research_question="Does error-aware recovery improve the reliability of tool-using AI agents compared with blind retry under a fixed tool-call budget?",
                objective="Measure recovery reliability under a fixed tool-call budget.",
                primary_outcome="Task success rate", budget_usd=10, max_runtime_minutes=30,
                constraints={"local_experiments": True}, stop_conditions=["Budget exhausted"],
            ))
            initial = derive_control_state(load_snapshot(ledger, project.project_id))
            planner = OmnigentPlanner()
            routing = await Orchestrator(ledger, planner).decide(project.project_id)
            decisions = ledger.list_decisions(project.project_id)
            events = ledger.list_events(project.project_id)
            assert len(decisions) == 1 and decisions[0].decision_id == routing.decision_id
            assert len(events) == 1 and events[0].payload["decision_id"] == routing.decision_id
            assert events[0].event_type == "PLANNER_DECISION"
        # Demonstrate actual durable writes after connection restart.
        with ResearchLedger(path) as ledger:
            assert ledger.list_decisions(project.project_id) == decisions
            assert ledger.list_events(project.project_id) == events
        print("AUTOLAB_PLANNER_OK")
        print(f"Project: {project.project_id}")
        print(f"State: {initial.value}")
        print(f"Action: {routing.action.value}")
        print(f"Target: {routing.target_role}")
        print("Decision persisted: yes")
        print("Event persisted: yes")
        print(f"Omnigent calls: {planner.calls}")


if __name__ == "__main__":
    asyncio.run(smoke())
