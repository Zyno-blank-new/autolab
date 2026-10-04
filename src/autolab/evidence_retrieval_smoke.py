"""Explicit live provider smoke; no model calls, PDFs, or ordinary pytest."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.evidence_smoke_helpers import create_project, verify_records
from autolab.literature.models import LiteratureLimits, SearchQuery
from autolab.literature.retrieval import LiteratureService
from autolab.literature.deduplicate import deduplicate
from autolab.literature.provenance import source_from_result


async def smoke():
    configure()
    queries = [SearchQuery(query="ReAct", purpose="Reasoning and acting methods for AI agents"),
               SearchQuery(query='"tool" AND "agents"', purpose="Tool-using agent methodologies")]
    service = LiteratureService(limits=LiteratureLimits(query_count=2, results_per_query_provider=5))
    batch = await service.retrieve(queries)
    unique = deduplicate(batch.results)
    # A provider's failure must not be mislabeled a successful two-provider smoke.
    if not all(batch.provider_counts.get(p, 0) > 0 for p in ("openalex", "arxiv")):
        raise RuntimeError(f"Live retrieval could not verify both providers: counts={batch.provider_counts}; warnings={batch.warnings}")
    with TemporaryDirectory(prefix="autolab-literature-") as directory:
        path = Path(directory) / "literature.db"
        with ResearchLedger(path) as ledger:
            project = create_project(ledger)
            for result in unique:
                ledger.add_source(source_from_result(result, project.project_id, ledger.next_id("SRC")))
            sources, _ = verify_records(ledger, project.project_id)
        with ResearchLedger(path) as ledger:
            assert verify_records(ledger, project.project_id)[0] == sources
        print("AUTOLAB_LITERATURE_OK")
        print(f"Queries: {len(queries)}")
        print(f"OpenAlex results: {batch.provider_counts['openalex']}")
        print(f"arXiv results: {batch.provider_counts['arxiv']}")
        print(f"Raw results: {len(batch.results)}")
        print(f"Deduplicated: {len(unique)}")
        print(f"Sources persisted: {len(sources)}")
        print(f"Warnings: {len(batch.warnings)}")


if __name__ == "__main__":
    asyncio.run(smoke())
