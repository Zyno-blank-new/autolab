"""Exact DOI/arXiv/title matching; no fuzzy merging."""
from .models import LiteratureResult
from .normalize import normalize_doi, normalize_arxiv_id, normalize_title


def same_paper(left, right) -> bool:
    ld, rd = normalize_doi(left.doi), normalize_doi(right.doi)
    la = getattr(left, "arxiv_id", None) or left.metadata.get("arxiv_id") or normalize_arxiv_id(left.url)
    ra = getattr(right, "arxiv_id", None) or right.metadata.get("arxiv_id") or normalize_arxiv_id(right.url)
    if ld and rd and ld == rd:
        return True
    if la and ra and la == ra:
        return True
    if ld and rd and ld != rd or la and ra and la != ra:
        return False
    lp = {(p.get("provider"), p.get("provider_id")) for p in left.metadata.get("provider_provenance", getattr(left, "provenance", []))}
    rp = {(p.get("provider"), p.get("provider_id")) for p in right.metadata.get("provider_provenance", getattr(right, "provenance", []))}
    if lp & rp:
        return True
    return bool(normalize_title(left.title)) and normalize_title(left.title) == normalize_title(right.title)


def merge(left: LiteratureResult, right: LiteratureResult) -> LiteratureResult:
    richer = right if len(right.abstract or "") > len(left.abstract or "") else left
    values = left.model_dump()
    for field in ("abstract", "pdf_url", "venue", "year", "doi", "arxiv_id", "citation_count"):
        values[field] = getattr(richer, field) if getattr(richer, field) is not None else getattr(right if richer is left else left, field)
    values["authors"] = right.authors if len(right.authors) > len(left.authors) else left.authors
    values["categories"] = sorted(set(left.categories + right.categories))
    metadata = left.metadata.get("provider_metadata", [left.metadata]) + right.metadata.get("provider_metadata", [right.metadata])
    values["metadata"] = {"provider_metadata": [m for n, m in enumerate(metadata) if m not in metadata[:n]]}
    values["provenance"] = [*left.provenance, *[p for p in right.provenance if p not in left.provenance]]
    return LiteratureResult.model_validate(values)


def deduplicate(results: list[LiteratureResult]) -> list[LiteratureResult]:
    unique = []
    for result in results:
        # Merge all matching groups, including aliases bridging DOI and arXiv.
        matches = [n for n, old in enumerate(unique) if same_paper(old, result)]
        if not matches:
            unique.append(result)
            continue
        combined = unique[matches[0]]
        for n in matches[1:]:
            combined = merge(combined, unique[n])
        unique[matches[0]] = merge(combined, result)
        for n in reversed(matches[1:]):
            del unique[n]
    return unique
