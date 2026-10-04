"""Bounded deterministic searches across independent official providers."""
import asyncio
from .models import LiteratureLimits, RetrievalBatch, SearchQuery
from .providers import OpenAlexProvider, ArxivProvider, ProviderError, ProviderUnavailable


class LiteratureService:
    def __init__(self, providers=None, limits: LiteratureLimits | None = None):
        self.providers = list(providers) if providers is not None else [OpenAlexProvider(), ArxivProvider()]
        self.limits = limits or LiteratureLimits()
        if not self.providers or len({p.name for p in self.providers}) != len(self.providers):
            raise ValueError("Provide at least one uniquely named literature provider")

    async def retrieve(self, queries: list[SearchQuery]) -> RetrievalBatch:
        if not 2 <= len(queries) <= self.limits.query_count:
            raise ValueError("Queries exceed configured retrieval bound")
        cap = min(self.limits.results_per_query_provider,
                  self.limits.max_raw_candidates // (len(queries)*len(self.providers)))
        if cap < 1:
            raise ValueError("Candidate budget too small for queries/providers")
        results, warnings, used = [], [], []
        counts = {p.name: 0 for p in self.providers}
        for query in queries:
            for provider in self.providers:
                try:
                    rows = await asyncio.to_thread(provider.search, query.query, cap)
                except ProviderError as error:
                    warnings.append(f"{provider.name}: {error}")
                    continue
                if provider.name not in used:
                    used.append(provider.name)
                rows = rows[:cap]
                results.extend(rows)
                counts[provider.name] += len(rows)
                warnings.extend(getattr(provider, "warnings", []))
        if not used:
            raise ProviderUnavailable("All literature providers failed; no evidence can be retrieved.")
        return RetrievalBatch(results=results, provider_counts=counts, providers_used=used, warnings=warnings)
