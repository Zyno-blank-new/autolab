"""Explicit paid question → real evidence → hypotheses/critique → PI smoke."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from autolab import schemas as s
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.evidence_smoke_helpers import create_project, verify_records
from autolab.evidence_integration_smoke import ObservedPlanner
from autolab.literature.models import LiteratureLimits
from autolab.literature.agent import OmnigentEvidenceAgent
from autolab.literature.service import EvidencePipeline
from autolab.hypotheses.agent import OmnigentHypothesisAgent, OmnigentScientificCritic
from autolab.hypotheses.service import HypothesisPipeline
from autolab.hypothesis_smoke_helpers import verify_hypotheses, write_artifact, print_candidates
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_hypothesis


async def smoke():
    configure()
    with TemporaryDirectory(prefix="autolab-hypothesis-loop-") as directory:
        path = Path(directory)/"loop.db"
        with ResearchLedger(path) as ledger:
            project = create_project(ledger)
            planner = ObservedPlanner()
            control = Orchestrator(ledger, planner)
            first = await control.decide(project.project_id)
            if first.action != s.PlannerAction.GATHER_EVIDENCE or first.target_role != "evidence":
                raise RuntimeError(f"Planner chose legal {first.action}; this smoke needs an actual evidence route")
            evidence_agent = OmnigentEvidenceAgent()
            evidence = await control.execute_evidence(first, EvidencePipeline(ledger, evidence_agent,
                limits=LiteratureLimits(query_count=2, results_per_query_provider=6, max_raw_candidates=24, top_k=3)))
            verify_records(ledger, project.project_id)
            if not evidence.evidence_ids:
                raise RuntimeError("No verified evidence available for a grounded hypothesis loop")
            second = await control.decide(project.project_id)
            if second.action != s.PlannerAction.GENERATE_HYPOTHESES or second.target_role != "hypothesis":
                raise RuntimeError(f"Planner chose legal {second.action}; this smoke needs an actual hypothesis route")
            agent, critic = OmnigentHypothesisAgent(), OmnigentScientificCritic()
            result = await control.execute_hypotheses(second, HypothesisPipeline(ledger, agent, critic))
            verify_hypotheses(ledger, project.project_id, result)
            third = await control.decide(project.project_id)
            context = planner.contexts[-1]
            assert {h["id"] for h in context.summaries["hypotheses"]} == set(result.hypothesis_ids)
            assert all(h["critic"] for h in context.summaries["hypotheses"])
            snapshot = load_snapshot(ledger, project.project_id)
            selected = selected_hypothesis(snapshot)
            if third.action == s.PlannerAction.DESIGN_EXPERIMENT and third.target_role == "experiment_designer":
                assert selected and selected.hypothesis_id in result.passed_hypothesis_ids
            assert not snapshot.experiments and not snapshot.candidates
            assert not any(e.actor == "experiment_designer" for e in snapshot.events)
            calls = {"evidence": evidence_agent.calls, "hypothesis": agent.calls, "critic": critic.calls, "planner": planner.calls}
            artifact = write_artifact("phase5-hypothesis-loop-smoke.json", ledger, project.project_id, result,
                model_calls=calls, planner_context=context.model_dump(mode="json"))
            print_candidates(ledger, result)
        with ResearchLedger(path) as reopened:
            assert load_snapshot(reopened, project.project_id) == snapshot
            verify_hypotheses(reopened, project.project_id, result)
        print("AUTOLAB_HYPOTHESIS_LOOP_OK")
        print(f"Decision 1: {first.action.value} → {first.target_role}")
        print(f"Evidence records: {len(evidence.evidence_ids)}")
        print(f"Decision 2: {second.action.value} → {second.target_role}")
        print(f"Hypotheses: {', '.join(result.hypothesis_ids)}")
        print(f"Critic reviews: {len(result.review_ids)}")
        print(f"Decision 3: {third.action.value} → {third.target_role}")
        print(f"Selected hypothesis: {selected.hypothesis_id + ' version ' + str(selected.version) if selected else 'none; Planner chose another action'}")
        print("Planner observed finalized hypotheses: yes")
        print("Experiment Designer executed: no")
        print(f"Model calls: {calls}; total {sum(calls.values())}")
        print(f"Scientific output for inspection: {artifact}")


if __name__ == "__main__":
    asyncio.run(smoke())
