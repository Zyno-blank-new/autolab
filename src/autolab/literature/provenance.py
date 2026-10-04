"""Verify provider identity and exact retrieved support before ledger writes."""
import hashlib
from autolab import schemas as s
from .models import LiteratureResult
from .normalize import normalize_doi, whitespace


class ProvenanceError(ValueError):
    pass


def abstract_digest(abstract: str | None) -> str:
    return hashlib.sha256(whitespace(abstract or "").encode()).hexdigest()


def source_from_result(result: LiteratureResult, project_id: str, source_id: str) -> s.SourceRecord:
    if not result.provenance or result.provider not in ("openalex", "arxiv"):
        raise ProvenanceError("Source lacks verified provider metadata")
    source = s.SourceRecord(source_id=source_id, project_id=project_id, title=result.title, authors=result.authors,
        year=result.year, doi=result.doi, url=result.url, provider=result.provider, abstract=result.abstract,
        metadata={"provider_id": result.provider_id, "arxiv_id": result.arxiv_id, "pdf_url": result.pdf_url,
                  "venue": result.venue, "citation_count": result.citation_count, "categories": result.categories,
                  "provider_provenance": result.provenance, "retrieval_metadata": result.metadata,
                  "abstract_sha256": abstract_digest(result.abstract), "content_level": "abstract"})
    validate_source(source)
    return source


def validate_source(source: s.SourceRecord) -> None:
    provenance = source.metadata.get("provider_provenance")
    if not isinstance(provenance, list) or not provenance:
        raise ProvenanceError("Source has no provider provenance")
    if any(not isinstance(p, dict) or p.get("provider") not in ("openalex", "arxiv") for p in provenance):
        raise ProvenanceError("Unknown bibliographic provider")
    endpoints = {"openalex": "https://api.openalex.org/works", "arxiv": "https://export.arxiv.org/api/query"}
    if any(p.get("endpoint") != endpoints[p["provider"]] for p in provenance):
        raise ProvenanceError("Provider provenance does not identify an official API")
    if not any(p["provider"] == source.provider and p.get("provider_id") == source.metadata.get("provider_id") for p in provenance):
        raise ProvenanceError("Source provider identity differs from retrieval provenance")
    checks = (("title", source.title), ("authors", source.authors), ("year", source.year), ("url", source.url))
    if any(not any(p.get(field) == value for p in provenance) for field, value in checks):
        raise ProvenanceError("Source bibliographic identity differs from provider metadata")
    if source.doi and not any(normalize_doi(p.get("doi")) == source.doi for p in provenance):
        raise ProvenanceError("Source DOI differs from provider metadata")
    digest = abstract_digest(source.abstract)
    if source.metadata.get("abstract_sha256") != digest or not any(p.get("abstract_sha256") == digest for p in provenance):
        raise ProvenanceError("Retrieved abstract content changed")


def validate_evidence(evidence: s.EvidenceRecord, source: s.SourceRecord | None) -> None:
    if not source or evidence.source_id != source.source_id or evidence.project_id != source.project_id:
        raise ProvenanceError("Evidence source does not exist in this project")
    validate_source(source)
    if evidence.location != "abstract":
        raise ProvenanceError("Only retrieved abstract support is accepted in Phase 4")
    supporting = whitespace(evidence.supporting_text)
    if not supporting or not source.abstract or supporting not in whitespace(source.abstract):
        raise ProvenanceError("Supporting text does not occur in the retrieved abstract")
