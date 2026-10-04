"""Atom API with serial, spaced requests; never downloads PDFs."""
import threading
import time
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from pydantic import ValidationError
from autolab.literature.models import LiteratureResult
from autolab.literature.normalize import normalize_arxiv_id, normalize_doi, safe_url, whitespace
from autolab.literature.provenance import abstract_digest
from .base import ProviderError, fetch, user_agent

ENDPOINT = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
_lock = threading.Lock()
_last_request = 0.0


def parse_feed(body: bytes, limit: int) -> tuple[list[LiteratureResult], list[str]]:
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ProviderError("Unsafe arXiv XML declaration")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise ProviderError("Malformed arXiv feed") from None
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise ProviderError("Expected arXiv Atom feed")
    results, warnings = [], []
    entries = root.findall("a:entry", NS)
    for entry in entries[:limit]:
        text = lambda name: whitespace(entry.findtext(name, "", NS))
        identifier = text("a:id")
        if "/api/errors" in identifier:
            raise ProviderError("arXiv API rejected the search query")
        try:
            arxiv_id = normalize_arxiv_id(identifier)
            if not arxiv_id:
                raise ValueError("Invalid arXiv ID")
            title = text("a:title")
            published = text("a:published")
            year = int(published[:4]) if published else None
            authors = [whitespace(a.findtext("a:name", "", NS)) for a in entry.findall("a:author", NS)]
            authors = [a for a in authors if a]
            links = entry.findall("a:link", NS)
            pdf = next((safe_url(l.get("href")) for l in links if l.get("title") == "pdf" or l.get("type") == "application/pdf"), None)
            doi = normalize_doi(text("x:doi"))
            url = safe_url(identifier)
            abstract = text("a:summary") or None
            results.append(LiteratureResult(provider="arxiv", provider_id=identifier, arxiv_id=arxiv_id,
                title=title, authors=authors, abstract=abstract, year=year, doi=doi, url=url,
                pdf_url=pdf, venue=text("x:journal_ref") or None,
                categories=[c.get("term") for c in entry.findall("a:category", NS) if c.get("term")],
                metadata={"published": published, "updated": text("a:updated")},
                provenance=[{"provider": "arxiv", "provider_id": identifier, "endpoint": ENDPOINT,
                             "title": title, "authors": authors, "year": year, "doi": doi, "url": url,
                             "abstract_sha256": abstract_digest(abstract)}]))
        except (ValidationError, ValueError, TypeError):
            warnings.append("Skipped malformed arXiv entry.")
    if entries and not results:
        raise ProviderError("arXiv returned only malformed records")
    return results, warnings


class ArxivProvider:
    name = "arxiv"
    def __init__(self, *, transport=fetch):
        self.transport = transport
        self.warnings = []
        self.cache = {}

    def search(self, query: str, limit: int, filters: dict | None = None) -> list[LiteratureResult]:
        if not 1 <= limit <= 15:
            raise ValueError("arXiv limit must be 1–15")
        if filters:
            raise ValueError("Use arXiv field prefixes in query; no additional filters supported")
        cache_key = (query, limit)
        if cache_key in self.cache:
            results, self.warnings = self.cache[cache_key]
            return list(results)
        # Unfielded queries are searched across all fields. Boolean queries
        # from the agent can use official ti:/abs:/all:/cat: syntax directly.
        search = query if any(prefix in query for prefix in ("all:", "ti:", "abs:", "cat:")) else f"all:({query})"
        params = {"search_query": search, "start": 0, "max_results": limit, "sortBy": "relevance", "sortOrder": "descending"}
        global _last_request
        with _lock:
            delay = max(0, 3.1 - (time.monotonic() - _last_request))
            if delay:
                time.sleep(delay)
            try:
                body = self.transport(ENDPOINT + "?" + urlencode(params), headers={"User-Agent": user_agent(), "Accept": "application/atom+xml"})
            finally:
                _last_request = time.monotonic()
        results, self.warnings = parse_feed(body, limit)
        self.cache[cache_key] = (results, list(self.warnings))
        return results
