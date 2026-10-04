"""Retrieval and handoff contracts; persistent records use canonical schemas."""
from enum import StrEnum
from pydantic import Field, model_validator
from autolab import schemas as s


class EvidenceRole(StrEnum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    BACKGROUND = "BACKGROUND"
    METHOD = "METHOD"
    UNKNOWN = "UNKNOWN"


class LiteratureResult(s.Record):
    provider: s.Text
    provider_id: s.Text
    title: s.Text
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    year: int | None = Field(default=None, ge=0, le=9999)
    doi: str | None = None
    arxiv_id: str | None = None
    url: s.Text
    pdf_url: str | None = None
    venue: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    categories: list[str] = Field(default_factory=list)
    metadata: s.JSON = Field(default_factory=dict)
    provenance: list[s.JSON] = Field(default_factory=list)


class SearchQuery(s.Record):
    query: str = Field(min_length=1, max_length=300)
    purpose: str = Field(min_length=1, max_length=500)


class QueryPlan(s.Record):
    inspect_existing_result: bool = False
    queries: list[SearchQuery] = Field(max_length=4)

    @model_validator(mode="after")
    def distinct_queries(self):
        if (self.inspect_existing_result and self.queries) or (not self.inspect_existing_result and len(self.queries) < 2):
            raise ValueError('Inspection requires no queries; literature requires 2–4 queries')
        if len({q.query.strip().casefold() for q in self.queries}) != len(self.queries):
            raise ValueError("Search queries must be distinct.")
        if any(not q.query.strip() for q in self.queries):
            raise ValueError("Blank query.")
        return self


class ScreenedPaper(s.Record):
    candidate_id: s.Text
    relevance_score: s.Score
    relevance_reason: str = Field(min_length=1, max_length=1000)
    evidence_role: EvidenceRole


class ScreeningResult(s.Record):
    papers: list[ScreenedPaper] = Field(max_length=80)


class ExtractedClaim(s.Record):
    candidate_id: s.Text
    claim: str = Field(min_length=1, max_length=1800)
    supporting_text: str = Field(min_length=1, max_length=3000)
    location: str = "abstract"
    confidence: s.Score
    evidence_role: EvidenceRole
    tags: list[str] = Field(default_factory=list, max_length=8)


class ExtractionResult(s.Record):
    evidence: list[ExtractedClaim] = Field(max_length=15)


class LiteratureLimits(s.Record):
    query_count: int = Field(default=3, ge=2, le=4)
    results_per_query_provider: int = Field(default=15, ge=1, le=15)
    max_raw_candidates: int = Field(default=60, ge=4, le=80)
    top_k: int = Field(default=4, ge=1, le=5)
    min_relevance: s.Score = 0.35
    abstract_chars: int = Field(default=1800, ge=200, le=4000)
    max_screen_chars: int = Field(default=90000, ge=4000, le=120000)


class RetrievalBatch(s.Record):
    results: list[LiteratureResult]
    provider_counts: dict[str, int]
    providers_used: list[str]
    warnings: list[str] = Field(default_factory=list)


class EvidenceGatheringResult(s.Record):
    project_id: s.Text
    queries: list[SearchQuery]
    providers_used: list[str]
    provider_counts: dict[str, int]
    raw_result_count: int
    deduplicated_count: int
    screened_count: int
    deeply_analyzed_count: int
    source_ids: list[str]
    evidence_ids: list[str]
    warnings: list[str]
    summary: s.Text
