"""Synthetic provider fixtures and fake Omnigent outputs: offline only."""
import asyncio
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
import pytest
from pydantic import ValidationError
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.literature.models import (QueryPlan, SearchQuery, ScreeningResult, ScreenedPaper, ExtractionResult,
    ExtractedClaim, LiteratureLimits, EvidenceRole as R)
from autolab.literature.providers import OpenAlexProvider, ArxivProvider, ProviderError, ProviderUnavailable
from autolab.literature.providers.openalex import normalize_work
from autolab.literature.providers.arxiv import parse_feed
from autolab.literature.providers import base
from autolab.literature.normalize import normalize_doi, normalize_arxiv_id, reconstruct_abstract, safe_url
from autolab.literature.deduplicate import deduplicate
from autolab.literature.provenance import source_from_result, validate_evidence, validate_source, ProvenanceError
from autolab.literature.retrieval import LiteratureService
from autolab.literature.screening import select_top_k, screening_candidates, EvidenceOutputError
from autolab.literature.service import EvidencePipeline
from autolab.literature.agent import OmnigentEvidenceAgent
from autolab.orchestration.orchestrator import Orchestrator, IllegalDecisionError
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.context_builder import ContextBuilder

FIXTURES = Path(__file__).parent / "fixtures/literature"


@pytest.fixture
def papers():
    raw = json.loads((FIXTURES / "openalex.json").read_text())
    oa = [normalize_work(w) for w in raw["results"][:3]]
    arxiv, _ = parse_feed((FIXTURES / "arxiv.xml").read_bytes(), 15)
    return oa + arxiv


@pytest.fixture
def project(ledger):
    return ledger.create_project(s.ResearchCharter(project_id=ledger.next_id("PROJECT"), title="Fixture research",
        research_question="Which methods improve reliability?", objective="Measure reliable task completion",
        primary_outcome="Task success", budget_usd=10, max_runtime_minutes=60))


class FakeProvider:
    def __init__(self, name, results=None, error=None):
        self.name, self.results, self.error = name, results or [], error
        self.warnings, self.calls = [], []
    def search(self, query, limit):
        self.calls.append((query, limit))
        if self.error:
            raise self.error
        return self.results[:limit]


class FakeEvidence:
    def __init__(self, mode="normal"):
        self.calls, self.mode = [], mode
    async def generate_queries(self, charter, query_count):
        self.calls.append("queries")
        return QueryPlan(queries=[SearchQuery(query=f"scientific query {n}", purpose="Prior knowledge") for n in range(query_count)])
    async def screen(self, charter, papers):
        self.calls.append("screen")
        return ScreeningResult(papers=[ScreenedPaper(candidate_id=p["candidate_id"], relevance_score=0.9,
            relevance_reason="Relevant fixture abstract", evidence_role=R.CONTRADICTING if "Limits" in p["title"] else R.METHOD)
            for p in papers])
    async def extract(self, charter, papers):
        self.calls.append("extract")
        return ExtractionResult(evidence=[ExtractedClaim(candidate_id=p["candidate_id"] if self.mode != "foreign" else "PAPER_FAKE",
            claim="The source reports: " + p["abstract"], supporting_text=p["abstract"] if self.mode != "unsupported" else "Invented passage",
            confidence=0.6, evidence_role=R(p["screening_role"])) for p in papers])


def pipeline(ledger, papers, mode="normal", providers=None, limits=None):
    limits = limits or LiteratureLimits(query_count=2, top_k=3)
    agent = FakeEvidence(mode)
    providers = providers if providers is not None else [FakeProvider("openalex", papers), FakeProvider("arxiv", papers)]
    return EvidencePipeline(ledger, agent, LiteratureService(providers, limits), limits)


def test_openalex_normalizes_and_skips_malformed():
    provider = OpenAlexProvider(transport=lambda *a, **k: (FIXTURES / "openalex.json").read_bytes(), api_key="")
    rows = provider.search("recovery", 15)
    assert len(rows) == 3 and len(provider.warnings) == 1
    assert rows[0].abstract == "Recovery improved task success in this benchmark."
    assert rows[0].doi == "10.1234/recovery" and rows[0].arxiv_id == "2401.00001"
    assert rows[0].citation_count == 12 and rows[0].venue == "Fixture Venue"
    assert rows[1].authors == [] and rows[1].doi is None
    assert rows[2].abstract is None and rows[2].year is None


def test_arxiv_atom_metadata(papers):
    row = papers[3]
    assert row.arxiv_id == "2401.00001" and row.year == 2024
    assert row.pdf_url == "https://arxiv.org/pdf/2401.00001v2" and row.categories == ["cs.AI"]
    assert row.metadata["updated"] == "2024-02-01T00:00:00Z"
    assert papers[4].doi is None


def test_openalex_null_optional_fields():
    record = normalize_work({"id": "https://openalex.org/W10001", "title": "Verified metadata",
        "authorships": None, "topics": None, "primary_location": None, "doi": None,
        "abstract_inverted_index": None, "publication_year": None})
    assert record.authors == [] and record.categories == [] and record.abstract is None


@pytest.mark.parametrize("value", ["https://doi.org/10.1234/ABC", "doi:10.1234/abc", "10.1234/abc", "http://dx.doi.org/10.1234/abc"])
def test_doi_forms(value):
    assert normalize_doi(value) == "10.1234/abc"


@pytest.mark.parametrize("value", ["2401.00001v3", "https://arxiv.org/abs/2401.00001v3", "https://arxiv.org/pdf/2401.00001v3.pdf"])
def test_arxiv_forms(value):
    assert normalize_arxiv_id(value) == "2401.00001"


@pytest.mark.parametrize("field", ["doi", "arxiv", "title"])
def test_deduplication_and_provider_provenance(papers, field):
    left, right = papers[0], papers[3]
    if field == "arxiv":
        right = right.model_copy(update={"doi": None, "title": "Other title"})
    if field == "title":
        left = left.model_copy(update={"doi": None, "arxiv_id": None})
        right = right.model_copy(update={"doi": None, "arxiv_id": None, "title": " TOOL recovery: study! "})
    rows = deduplicate([left, right])
    assert len(rows) == 1 and len(rows[0].provenance) == 2


def test_similar_titles_not_merged(papers):
    assert len(deduplicate([papers[0], papers[0].model_copy(update={"doi": None, "arxiv_id": None,
        "url": "https://example.org/other", "title": "Tool Recovery Study with Different Metrics",
        "provider_id": "https://openalex.org/W99999", "provenance": []})])) == 2
    assert len(deduplicate([papers[0], papers[0].model_copy(update={"doi": "10.1234/other", "arxiv_id": None,
        "url": "https://example.org/other"})])) == 2


@pytest.mark.parametrize("body", [b"not json", b'{"results":null}', b'{}'])
def test_openalex_malformed_response(body):
    with pytest.raises(ProviderError):
        OpenAlexProvider(transport=lambda *a, **k: body).search("query", 3)


@pytest.mark.parametrize("body", [b"not XML", b"<html/>", b'<!DOCTYPE foo><feed/>', b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#bad</id></entry></feed>'])
def test_arxiv_malformed_response(body):
    with pytest.raises(ProviderError):
        parse_feed(body, 3)


@pytest.mark.parametrize("error", [TimeoutError(), URLError("private URL"), HTTPError("https://example.org?api_key=private", 429, "rate limit", {}, None)])
def test_http_errors_are_bounded_and_redacted(monkeypatch, error):
    calls = []
    def fail(*a, **k):
        calls.append(1)
        raise error
    monkeypatch.setattr(base, "urlopen", fail)
    with pytest.raises(ProviderError) as raised:
        base.fetch("https://api.openalex.org/works", headers={})
    assert len(calls) == 1 and "private" not in str(raised.value)


def test_provider_errors_propagate_without_retry():
    def fail(*a, **k):
        raise ProviderError("Timeout")
    with pytest.raises(ProviderError):
        OpenAlexProvider(transport=fail).search("query", 2)


def test_arxiv_etiquette_and_query_cache(monkeypatch):
    from autolab.literature.providers import arxiv
    waits, calls = [], []
    monkeypatch.setattr(arxiv, "_last_request", 10)
    monkeypatch.setattr(arxiv.time, "monotonic", lambda: 11)
    monkeypatch.setattr(arxiv.time, "sleep", waits.append)
    def transport(*args, **kwargs):
        calls.append(args[0])
        return (FIXTURES / "arxiv.xml").read_bytes()
    provider = ArxivProvider(transport=transport)
    provider.search("query", 2)
    provider.search("query", 2)
    assert len(calls) == 1 and waits[0] >= 2
    assert "start=0" in calls[0] and "max_results=2" in calls[0]


def test_openalex_credentials_not_in_query_or_metadata():
    capture = []
    def transport(url, **kwargs):
        capture.append((url, kwargs))
        return (FIXTURES / "openalex.json").read_bytes()
    rows = OpenAlexProvider(transport=transport, api_key="private-key").search("query", 2)
    assert "private-key" not in capture[0][0]
    assert capture[0][1]["headers"]["Authorization"] == "Bearer private-key"
    assert "private-key" not in rows[0].model_dump_json()


def test_provenance_source_metadata_and_support(papers):
    source = source_from_result(papers[0], "PROJECT_TEST", "SRC_TEST")
    validate_source(source)
    evidence = s.EvidenceRecord(evidence_id="EVID_TEST", project_id="PROJECT_TEST", source_id=source.source_id,
        claim="Source reports improved success", supporting_text="Recovery improved\n task success", location="abstract")
    validate_evidence(evidence, source)
    assert source.title == papers[0].title and source.metadata["content_level"] == "abstract"


@pytest.mark.parametrize("change", [{"supporting_text":"invented quotation"}, {"supporting_text":""}, {"location":None}, {"location":"page 4"}, {"source_id":"SRC_MISSING"}, {"project_id":"PROJECT_OTHER"}])
def test_unsupported_evidence_rejected(papers, change):
    source = source_from_result(papers[0], "PROJECT_TEST", "SRC_TEST")
    record = s.EvidenceRecord(evidence_id="EVID_TEST", project_id="PROJECT_TEST", source_id=source.source_id,
        claim="Source-reported finding", supporting_text=source.abstract, location="abstract").model_copy(update=change)
    with pytest.raises(ProvenanceError):
        validate_evidence(record, source)
    with pytest.raises(ProvenanceError):
        validate_evidence(record, None)


@pytest.mark.parametrize("change", [{"title":"Fabricated title"}, {"authors":["Invented Author"]}, {"doi":"10.1234/invented"}, {"year":1990}, {"abstract":"Fake abstract"}, {"url":"https://fake.org"}])
def test_fabricated_bibliography_rejected(papers, change):
    source = source_from_result(papers[0], "PROJECT_TEST", "SRC_TEST").model_copy(update=change)
    with pytest.raises(ProvenanceError):
        validate_source(source)


def test_provider_abstract_cannot_be_replaced_even_with_new_local_hash(papers):
    from autolab.literature.provenance import abstract_digest
    source = source_from_result(papers[0], "PROJECT_TEST", "SRC_TEST")
    source = source.model_copy(update={"abstract": "Invented content", "metadata": {
        **source.metadata, "abstract_sha256": abstract_digest("Invented content")}})
    with pytest.raises(ProvenanceError):
        validate_source(source)
    with pytest.raises(ProvenanceError):
        source_from_result(papers[0].model_copy(update={"abstract": "Invented content"}), "PROJECT_TEST", "SRC_TEST")


@pytest.mark.parametrize("field,value", [("provider", "unknown"), ("provider_id", "fabricated")])
def test_source_provider_identity_is_verified(papers, field, value):
    source = source_from_result(papers[0], "PROJECT_TEST", "SRC_TEST")
    changes = {"provider": value} if field == "provider" else {"metadata": {**source.metadata, field: value}}
    with pytest.raises(ProvenanceError):
        validate_source(source.model_copy(update=changes))


def test_agent_schema_cannot_supply_bibliography():
    with pytest.raises(ValidationError):
        ExtractedClaim(candidate_id="PAPER_1", claim="claim", supporting_text="text", confidence=0.5,
                       evidence_role="METHOD", title="Fabricated source", doi="10.1234/fake")


def test_top_k_preserves_contradictory_work(papers):
    candidates = screening_candidates(deduplicate(papers), LiteratureLimits())
    items = [ScreenedPaper(candidate_id=k, relevance_score=0.5 if "Limits" in p.title else 0.95,
        relevance_reason="Relevant", evidence_role=R.CONTRADICTING if "Limits" in p.title else R.SUPPORTING)
        for k, (p, _) in candidates.items()]
    chosen = select_top_k(ScreeningResult(papers=items), candidates, LiteratureLimits(top_k=2))
    assert len(chosen) == 2 and any(p.evidence_role == R.CONTRADICTING for p in chosen)
    with pytest.raises(EvidenceOutputError):
        select_top_k(ScreeningResult(papers=items[:-1]), candidates, LiteratureLimits())


def test_screening_excludes_missing_abstract_and_bounds_context(papers):
    candidates = screening_candidates(papers, LiteratureLimits(abstract_chars=200))
    assert len(candidates) == 4 and all(len(row["abstract"]) <= 200 for _, row in candidates.values())


def test_retrieval_bounds(papers):
    providers = [FakeProvider("openalex", papers*20), FakeProvider("arxiv", papers*20)]
    service = LiteratureService(providers, LiteratureLimits(query_count=4, max_raw_candidates=60))
    queries = [SearchQuery(query=f"query {n}", purpose="Knowledge") for n in range(4)]
    batch = asyncio.run(service.retrieve(queries))
    assert len(batch.results) <= 60 and all(limit <= 15 for p in providers for _, limit in p.calls)


def test_pipeline_persistence_reuse_and_restart(ledger, project, papers):
    flow = pipeline(ledger, papers)
    first = asyncio.run(flow.gather(project.project_id))
    second = asyncio.run(flow.gather(project.project_id))
    assert len(first.source_ids) == 3 and len(first.evidence_ids) == 3
    assert first.source_ids == second.source_ids and first.evidence_ids == second.evidence_ids
    assert len(ledger.list_sources(project.project_id)) == 3 and len(ledger.list_evidence(project.project_id)) == 3
    for record in ledger.list_evidence(project.project_id):
        validate_evidence(record, ledger.get(s.SourceRecord, record.source_id))
    with ResearchLedger(ledger.database.path) as reopened:
        assert reopened.list_evidence(project.project_id) == ledger.list_evidence(project.project_id)
    context = ContextBuilder().build(load_snapshot(ledger, project.project_id))
    assert len(context.summaries["evidence"]) == 3
    assert '"abstract"' not in context.model_dump_json()
    assert flow.agent.calls == ["queries", "screen", "extract"]*2


def test_one_provider_failure_degrades(ledger, project, papers):
    flow = pipeline(ledger, papers, providers=[FakeProvider("openalex", error=ProviderError("unavailable")), FakeProvider("arxiv", papers)])
    result = asyncio.run(flow.gather(project.project_id))
    assert result.providers_used == ["arxiv"] and result.evidence_ids and result.warnings


def test_both_provider_failures_are_explicit(ledger, project, papers):
    providers = [FakeProvider(name, error=ProviderError("timeout")) for name in ("openalex", "arxiv")]
    with pytest.raises(ProviderUnavailable):
        asyncio.run(pipeline(ledger, papers, providers=providers).gather(project.project_id))
    assert not ledger.list_sources(project.project_id) and not ledger.list_evidence(project.project_id)
    assert ledger.list_events(project.project_id)[-1].event_type == "EVIDENCE_GATHERING_FAILED"


def test_zero_results_do_not_fabricate(ledger, project):
    flow = pipeline(ledger, [], providers=[FakeProvider("openalex"), FakeProvider("arxiv")])
    result = asyncio.run(flow.gather(project.project_id))
    assert not result.source_ids and not result.evidence_ids and result.warnings
    assert flow.agent.calls == ["queries"]
    assert ledger.list_events(project.project_id)[-1].event_type == "EVIDENCE_GATHERING_COMPLETED"


def test_unsupported_claims_not_persisted(ledger, project, papers):
    result = asyncio.run(pipeline(ledger, papers, "unsupported").gather(project.project_id))
    assert result.source_ids and not result.evidence_ids
    assert not ledger.list_evidence(project.project_id)


def test_unknown_model_source_fails(ledger, project, papers):
    with pytest.raises(EvidenceOutputError):
        asyncio.run(pipeline(ledger, papers, "foreign").gather(project.project_id))
    assert not ledger.list_sources(project.project_id)


class FakePlanner:
    def __init__(self, actions):
        self.actions, self.contexts = list(actions), []
    async def propose(self, context, decision_id, feedback=None):
        self.contexts.append(context)
        action, target = self.actions.pop(0)
        return s.NextDecision(decision_id=decision_id, project_id=context.charter.project_id, action=action,
            target_agent=target, reason="Fixture PI choice", remaining_budget_usd=context.budget.remaining_budget_usd).model_dump_json()


@pytest.mark.parametrize("second,target", [(s.PlannerAction.GENERATE_HYPOTHESES,"hypothesis"), (s.PlannerAction.GATHER_EVIDENCE,"evidence"), (s.PlannerAction.STOP,None)])
def test_adaptive_handoff_does_not_force_next_action(ledger, project, papers, second, target):
    planner = FakePlanner([(s.PlannerAction.GATHER_EVIDENCE, "evidence"), (second, target)])
    control = Orchestrator(ledger, planner)
    async def run():
        route = await control.decide(project.project_id)
        result = await control.execute_evidence(route, pipeline(ledger, papers))
        assert result.evidence_ids and len(planner.contexts) == 1
        with pytest.raises(IllegalDecisionError, match="already completed"):
            await control.execute_evidence(route, pipeline(ledger, papers))
        return await control.decide(project.project_id)
    route = asyncio.run(run())
    assert route.action == second and planner.contexts[1].counts["evidence"] == 3


def test_pause_blocks_evidence_dispatch(ledger, project, papers):
    control = Orchestrator(ledger, FakePlanner([(s.PlannerAction.GATHER_EVIDENCE,"evidence")]))
    route = asyncio.run(control.decide(project.project_id))
    ledger.add_event(s.EventRecord(event_id=ledger.next_id("EVENT"), project_id=project.project_id,
        event_type="PROJECT_PAUSED", actor="human", summary="Pause"))
    with pytest.raises(IllegalDecisionError):
        asyncio.run(control.execute_evidence(route, pipeline(ledger, papers)))


def test_agent_invokes_evidence_yaml_and_requires_json(project, monkeypatch):
    agent = OmnigentEvidenceAgent()
    captured = []
    async def invoke(path, prompt, **kwargs):
        captured.append((path, json.loads(prompt), kwargs))
        return '{"queries":[{"query":"core phenomenon","purpose":"core"},{"query":"baseline evaluation","purpose":"method"}]}'
    monkeypatch.setattr(agent.transport, "invoke_agent", invoke)
    plan = asyncio.run(agent.generate_queries(project, 2))
    assert len(plan.queries) == 2 and captured[0][0].name == "evidence.yaml"
    assert captured[0][2]["role"] == "evidence"
    async def bad(*a, **k):
        return "Fabricated prose"
    monkeypatch.setattr(agent.transport, "invoke_agent", bad)
    with pytest.raises(EvidenceOutputError):
        asyncio.run(agent.generate_queries(project, 2))
