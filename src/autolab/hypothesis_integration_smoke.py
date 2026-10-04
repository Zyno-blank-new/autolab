"""Explicit paid Hypothesis/Scientific Critic smoke over real abstract evidence."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from autolab import schemas as s
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.evidence_smoke_helpers import create_project
from autolab.literature.models import LiteratureLimits, SearchQuery
from autolab.literature.retrieval import LiteratureService
from autolab.literature.deduplicate import deduplicate
from autolab.literature.provenance import source_from_result, validate_evidence
from autolab.hypotheses.agent import OmnigentHypothesisAgent, OmnigentScientificCritic
from autolab.hypotheses.service import HypothesisPipeline
from autolab.hypothesis_smoke_helpers import verify_hypotheses, write_artifact, print_candidates


async def seed_real_evidence(ledger, project):
    # Known demo keywords live in this isolated smoke only, never agent prompts.
    limits = LiteratureLimits(query_count=2, results_per_query_provider=2, max_raw_candidates=8, top_k=3)
    batch = await LiteratureService(limits=limits).retrieve([
        SearchQuery(query="ReAct", purpose="Prior work on agent reasoning and action"),
        SearchQuery(query="Reflexion", purpose="Prior work on feedback and agent recovery")])
    papers = [p for p in deduplicate(batch.results) if p.abstract]
    # Prefer retrieved work whose title matches the demo keyword; no new metadata.
    papers.sort(key=lambda p: (not any(term in p.title.casefold() for term in ("react:", "reflexion:")), p.title))
    if len(papers) < 2:
        raise RuntimeError("Insufficient real retrieved abstract evidence for the hypothesis smoke")
    for paper in papers[:3]:
        source = source_from_result(paper, project.project_id, ledger.next_id("SRC"))
        supporting = source.abstract[:1200]
        evidence = s.EvidenceRecord(evidence_id=ledger.next_id("EVID"), project_id=project.project_id,
            source_id=source.source_id, claim="The publication abstract reports: " + supporting,
            supporting_text=supporting, location="abstract", confidence=0.5, tags=["BACKGROUND", "ABSTRACT_ONLY"])
        validate_evidence(evidence, source)
        ledger.add_many([source, evidence])
    return batch


async def smoke():
    configure()
    with TemporaryDirectory(prefix="autolab-hypothesis-") as directory:
        path = Path(directory)/"hypothesis.db"
        with ResearchLedger(path) as ledger:
            project = create_project(ledger)
            retrieval = await seed_real_evidence(ledger, project)
            agent, critic = OmnigentHypothesisAgent(), OmnigentScientificCritic()
            result = await HypothesisPipeline(ledger, agent, critic).generate(project.project_id)
            history = verify_hypotheses(ledger, project.project_id, result)
            evidence_count = len(ledger.list_evidence(project.project_id))
            artifact = write_artifact("phase5-hypothesis-smoke.json", ledger, project.project_id, result,
                model_calls={"hypothesis": agent.calls, "critic": critic.calls, "planner": 0},
                retrieval_warnings=retrieval.warnings)
            print_candidates(ledger, result)
        with ResearchLedger(path) as reopened:
            assert verify_hypotheses(reopened, project.project_id, result) == history
        print("AUTOLAB_HYPOTHESIS_OK")
        print(f"Project: {project.project_id}")
        print(f"Evidence records: {evidence_count}")
        print(f"Hypotheses generated: {len(result.hypothesis_ids)}")
        print("All evidence IDs valid: yes")
        print("Reviews persisted: yes")
        print("Version history valid: yes")
        print(f"Revision rounds: {result.revision_rounds}")
        print(f"Hypothesis model calls: {agent.calls}")
        print(f"Critic model calls: {critic.calls}")
        print(f"Scientific output for inspection: {artifact}")


if __name__ == "__main__":
    asyncio.run(smoke())
