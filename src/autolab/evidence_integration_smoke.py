"""Explicit paid Omnigent evidence smoke, optionally with both PI cycles."""
import argparse
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.evidence_smoke_helpers import create_project, verify_records
from autolab.literature.agent import OmnigentEvidenceAgent
from autolab.literature.models import LiteratureLimits
from autolab.literature.service import EvidencePipeline
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.orchestrator import Orchestrator
from autolab.planner import OmnigentPlanner
from autolab.schemas import PlannerAction as A


class ObservedPlanner(OmnigentPlanner):
    def __init__(self):
        super().__init__()
        self.contexts = []
    async def propose(self, context, decision_id, feedback=None):
        self.contexts.append(context)
        return await super().propose(context, decision_id, feedback)


async def smoke(*, with_planner=False):
    configure()
    with TemporaryDirectory(prefix="autolab-evidence-") as directory:
        path = Path(directory) / "evidence.db"
        with ResearchLedger(path) as ledger:
            project = create_project(ledger)
            agent = OmnigentEvidenceAgent()
            pipeline = EvidencePipeline(ledger, agent, limits=LiteratureLimits(query_count=2,
                results_per_query_provider=10, max_raw_candidates=40, top_k=3))
            planner, first, second = None, None, None
            if with_planner:
                planner = ObservedPlanner()
                control = Orchestrator(ledger, planner)
                first = await control.decide(project.project_id)
                if first.action != A.GATHER_EVIDENCE or first.target_role != "evidence":
                    raise RuntimeError(f"Planner chose legal {first.action}; this handoff smoke requires an actual evidence route.")
                result = await control.execute_evidence(first, pipeline)
            else:
                result = await pipeline.gather(project.project_id)
            sources, evidence = verify_records(ledger, project.project_id)
            if not sources or not evidence:
                raise RuntimeError("No traceable evidence found; cannot certify the live evidence smoke.")
            context = ContextBuilder().build(load_snapshot(ledger, project.project_id))
            assert context.counts["evidence"] == len(evidence) and context.summaries["evidence"]
            if with_planner:
                second = await control.decide(project.project_id)
                assert planner.contexts[-1].counts["evidence"] == len(evidence)
        with ResearchLedger(path) as ledger:
            reopened_sources, reopened_evidence = verify_records(ledger, project.project_id)
            assert sources == reopened_sources and evidence == reopened_evidence
        print("AUTOLAB_EVIDENCE_OK")
        print(f"Project: {project.project_id}")
        print(f"Providers: {', '.join(result.providers_used)}")
        print(f"Provider counts: {result.provider_counts}")
        print(f"Raw papers: {result.raw_result_count}")
        print(f"Deduplicated: {result.deduplicated_count}")
        print(f"Screened: {result.screened_count}")
        print(f"Deep analyzed: {result.deeply_analyzed_count}")
        print(f"Sources persisted: {len(sources)}")
        print(f"Evidence records: {len(evidence)}")
        print("All evidence traceable: yes")
        print(f"Evidence model calls: {agent.calls}")
        print(f"Warnings: {result.warnings}")
        if with_planner:
            print("AUTOLAB_EVIDENCE_LOOP_OK")
            print(f"Decision 1: {first.action.value} → {first.target_role}")
            print(f"Evidence added: {len(evidence)} records")
            print(f"Decision 2: {second.action.value} → {second.target_role}")
            print("Planner observed updated evidence: yes")
            print(f"Planner model calls: {planner.calls}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-planner", action="store_true", help="Also verify actual Planner → evidence → Planner handoff")
    asyncio.run(smoke(with_planner=parser.parse_args().with_planner))
