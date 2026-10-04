"""OpenAlex works search; see https://help.openalex.org/api/."""
import json
import os
import re
from urllib.parse import urlencode
from pydantic import ValidationError
from autolab.literature.models import LiteratureResult
from autolab.literature.normalize import normalize_doi, normalize_arxiv_id, reconstruct_abstract, safe_url, whitespace
from autolab.literature.provenance import abstract_digest
from .base import ProviderError, fetch, user_agent

ENDPOINT = "https://api.openalex.org/works"


def normalize_work(work: dict) -> LiteratureResult:
    identifier = work["id"]
    if not isinstance(identifier, str) or not re.fullmatch(r"https://openalex.org/W\d+", identifier):
        raise ValueError("Invalid OpenAlex ID")
    title = whitespace(work.get("title") or work.get("display_name") or "")
    location = work.get("primary_location") or {}
    url = safe_url(location.get("landing_page_url")) or safe_url(work.get("doi")) or identifier
    locations = work.get("locations") or []
    arxiv = next((a for loc in [location, *locations] if isinstance(loc, dict)
                  for a in [normalize_arxiv_id(loc.get("landing_page_url"))] if a), None)
    authors = [whitespace(a["author"]["display_name"]) for a in (work.get("authorships") or [])
               if isinstance(a, dict) and isinstance(a.get("author"), dict) and a["author"].get("display_name")]
    doi = normalize_doi(work.get("doi"))
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    venue = (location.get("source") or {}).get("display_name")
    categories = [t["display_name"] for t in (work.get("topics") or []) if isinstance(t, dict) and t.get("display_name")]
    oa = work.get("open_access") or {}
    metadata = {"publication_date": work.get("publication_date"), "open_access": {
        "is_oa": oa.get("is_oa"), "oa_status": oa.get("oa_status"), "oa_url": safe_url(oa.get("oa_url"))}}
    return LiteratureResult(provider="openalex", provider_id=identifier, title=title, authors=authors,
        abstract=abstract, year=work.get("publication_year"), doi=doi, arxiv_id=arxiv, url=url,
        pdf_url=safe_url(location.get("pdf_url")), venue=venue, citation_count=work.get("cited_by_count"),
        categories=categories, metadata=metadata,
        provenance=[{"provider": "openalex", "provider_id": identifier, "endpoint": ENDPOINT,
                     "title": title, "authors": authors, "year": work.get("publication_year"), "doi": doi, "url": url,
                     "abstract_sha256": abstract_digest(abstract)}])


class OpenAlexProvider:
    name = "openalex"
    def __init__(self, *, transport=fetch, api_key: str | None = None, contact: str | None = None):
        self.transport = transport
        self.api_key = api_key if api_key is not None else os.environ.get("OPENALEX_API_KEY", "")
        self.contact = contact or os.environ.get("AUTOLAB_CONTACT_EMAIL")
        self.warnings = []

    def search(self, query: str, limit: int, filters: dict | None = None) -> list[LiteratureResult]:
        if not 1 <= limit <= 15:
            raise ValueError("OpenAlex limit must be 1–15")
        params = {"search": query, "per_page": limit, "page": 1}
        if filters:
            if set(filters) - {"from_publication_date", "to_publication_date", "is_oa"}:
                raise ValueError("Unsupported OpenAlex filter")
            params["filter"] = ",".join(f"{k}:{str(v).lower()}" for k, v in filters.items())
        headers = {"User-Agent": user_agent(self.contact), "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self.warnings = []
        raw = self.transport(ENDPOINT + "?" + urlencode(params), headers=headers)
        try:
            payload = json.loads(raw)
            works = payload["results"]
            if not isinstance(works, list):
                raise ValueError("Invalid results")
        except (ValueError, KeyError, TypeError):
            raise ProviderError("Malformed OpenAlex response") from None
        results = []
        for work in works[:limit]:
            try:
                results.append(normalize_work(work))
            except (ValidationError, ValueError, KeyError, TypeError, AttributeError):
                self.warnings.append("Skipped malformed OpenAlex work.")
        if works and not results:
            raise ProviderError("OpenAlex returned only malformed records")
        return results
