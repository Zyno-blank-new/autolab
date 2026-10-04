"""Query → retrieve → screen → extract → verify → persist, under PI control."""
from typing import Protocol
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.budget import calculate_budget
from autolab.planner.service import PlannerInvocationError, runtime_metadata
from .agent import OmnigentEvidenceAgent
from .deduplicate import deduplicate, same_paper
from .models import EvidenceGatheringResult, LiteratureLimits
from .provenance import source_from_result, validate_evidence, ProvenanceError
from .retrieval import LiteratureService
from .screening import EvidenceOutputError, screening_candidates, select_top_k
from .providers import ProviderError


class EvidenceAgent(Protocol):
    async def generate_queries(self, charter, query_count): ...
    async def screen(self, charter, papers): ...
    async def extract(self, charter, papers): ...


class EvidencePipeline:
    def __init__(self, ledger: ResearchLedger, agent: EvidenceAgent | None = None,
                 retrieval: LiteratureService | None = None, limits: LiteratureLimits | None = None):
        self.ledger = ledger
        self.limits = limits or LiteratureLimits()
        self.agent = agent if agent is not None else OmnigentEvidenceAgent()
        self.retrieval = retrieval if retrieval is not None else LiteratureService(limits=self.limits)

    def _allowed(self, project_id):
        snapshot = load_snapshot(self.ledger, project_id)
        result = DecisionValidator().validate(s.NextDecision(decision_id="DEC_EVIDENCE_GATE", project_id=project_id,
            action=s.PlannerAction.GATHER_EVIDENCE, target_agent="evidence", reason="Check evidence dispatch gate",
            remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd), snapshot)
        if not result.valid:
            raise EvidenceOutputError("Evidence workflow blocked: " + "; ".join(result.reasons))
        return snapshot

    def _event(self, project_id, kind, summary, payload=None, target_id=None):
        payload = dict(payload or {})
        if kind in ("LITERATURE_SEARCH_COMPLETED", "EVIDENCE_ADDED", "EVIDENCE_GATHERING_COMPLETED"):
            metadata = runtime_metadata(self.agent)
            if metadata:
                payload["model_metadata"] = metadata
        return s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id,
            event_type=kind, actor="evidence", summary=summary, payload=payload, target_id=target_id,
            target_type=("sources" if kind == "SOURCE_ADDED" else "evidence") if target_id else None)

    async def gather(self, project_id: str) -> EvidenceGatheringResult:
        snapshot = self._allowed(project_id)
        self.ledger.add_event(self._event(project_id, "LITERATURE_SEARCH_STARTED", "Starting bounded literature gathering"))
        try:
            return await self._gather(snapshot)
        except (ProviderError, EvidenceOutputError, PlannerInvocationError, ProvenanceError):
            # Fail visibly with no raw model output, credentials, or HTTP URLs.
            self.ledger.add_event(self._event(project_id, "EVIDENCE_GATHERING_FAILED", "Literature/evidence workflow failed; no unsupported evidence accepted"))
            raise

    async def _gather(self, snapshot):
        charter = snapshot.charter
        project_id = charter.project_id
        from autolab.orchestration.adaptive import result_packet
        adaptive = result_packet(snapshot)
        if adaptive:
            adaptive['known_sources'] = [{'id': x.source_id, 'title': x.title[:240]} for x in snapshot.sources[-20:]]
            adaptive['known_evidence'] = [{'id': x.evidence_id, 'claim': x.claim[:320], 'tags': x.tags} for x in snapshot.evidence[-20:]]
        plan = await self.agent.generate_adaptive_queries(charter, self.limits.query_count, adaptive) if adaptive else await self.agent.generate_queries(charter, self.limits.query_count)
        if plan.inspect_existing_result:
            if not adaptive:
                raise EvidenceOutputError('Existing-result inspection requires current reviewed evidence')
            from .result_inspection import inspect_result
            inspection = inspect_result(snapshot)
            result = EvidenceGatheringResult(project_id=project_id, queries=[], providers_used=[], provider_counts={},
                raw_result_count=0, deduplicated_count=0, screened_count=0, deeply_analyzed_count=0,
                source_ids=[], evidence_ids=[], warnings=['Existing artifacts inspected; no new publication, measurements or ScientificAnalysis created.'],
                summary='Inspected complete bounded paired observation identity/coverage and original resource bindings; return to Planner.')
            records = [self._event(project_id, 'LOCAL_RESULT_EVIDENCE_INSPECTED', result.summary, inspection),
                       self._event(project_id, 'EVIDENCE_GATHERING_COMPLETED', result.summary, result.model_dump(mode='json'))]
            def recheck_inspection():
                from autolab.orchestration.adaptive import state_pin
                fresh = self._allowed(project_id)
                if state_pin(fresh) != state_pin(snapshot) or inspect_result(fresh) != inspection:
                    raise EvidenceOutputError('Existing result changed during inspection')
            self.ledger.add_many(records, check=recheck_inspection)
            return result
        self._allowed(project_id)
        batch = await self.retrieval.retrieve(plan.queries)
        unique = deduplicate(batch.results)
        self.ledger.add_event(self._event(project_id, "LITERATURE_SEARCH_COMPLETED", "Official scholarly retrieval completed",
            {"provider_counts": batch.provider_counts, "raw_count": len(batch.results), "deduplicated_count": len(unique)}))
        warnings = list(batch.warnings)
        # When reusing an immutable source, the model must see its preserved
        # abstract; support cannot be silently swapped to a different revision.
        existing = self.ledger.list_sources(project_id)
        for n, paper in enumerate(unique):
            old = next((source for source in existing if same_paper(source, paper)), None)
            if old:
                unique[n] = paper.model_copy(update={"abstract": old.abstract})
        if adaptive:
            # Known immutable sources stay in history but do not consume a new deep call.
            unique = [paper for paper in unique if not any(same_paper(source, paper) for source in existing)]
        candidates = screening_candidates(unique, self.limits)
        if len(candidates) < len(unique):
            warnings.append("Candidates without usable abstracts or exceeding context bounds were excluded from analysis.")
        screened_count, deep_count = 0, 0
        selected, extraction = [], None
        if candidates:
            self._allowed(project_id)
            screening = await self.agent.screen(charter, [row for _, row in candidates.values()])
            selected = select_top_k(screening, candidates, self.limits)
            screened_count = len(screening.papers)
            if selected:
                self._allowed(project_id)
                papers = [{**candidates[p.candidate_id][1], "screening_role": p.evidence_role.value} for p in selected]
                extraction = await self.agent.extract(charter, papers)
                deep_count = len(selected)
                selected_ids = {p.candidate_id for p in selected}
                if any(c.candidate_id not in selected_ids for c in extraction.evidence):
                    raise EvidenceOutputError("Extraction cites an unknown or unselected candidate")
                if len(extraction.evidence) > 2*len(selected):
                    raise EvidenceOutputError("Extraction exceeds the per-selection claim bound")
        sources, new_sources, records, evidence_ids = {}, [], [], []
        for paper in selected:
            result = candidates[paper.candidate_id][0]
            old = next((source for source in existing if same_paper(source, result)), None)
            source = old or source_from_result(result, project_id, self.ledger.next_id("SRC"))
            sources[paper.candidate_id] = source
            if old is None:
                new_sources.append(source)
        known_evidence = self.ledger.list_evidence(project_id)
        for claim in extraction.evidence if extraction else []:
            source = sources[claim.candidate_id]
            evidence = s.EvidenceRecord(evidence_id=self.ledger.next_id("EVID"), project_id=project_id,
                source_id=source.source_id, claim=claim.claim, supporting_text=claim.supporting_text,
                location=claim.location, confidence=claim.confidence,
                tags=[claim.evidence_role.value, "ABSTRACT_ONLY", *claim.tags])
            try:
                validate_evidence(evidence, source)
            except ProvenanceError:
                warnings.append(f"Rejected unsupported extracted claim for {claim.candidate_id}.")
                continue
            duplicate = next((e for e in [*known_evidence, *records] if e.source_id == evidence.source_id
                              and e.claim == evidence.claim and e.supporting_text == evidence.supporting_text), None)
            if duplicate:
                if duplicate.evidence_id not in evidence_ids:
                    evidence_ids.append(duplicate.evidence_id)
            else:
                records.append(evidence)
                evidence_ids.append(evidence.evidence_id)
        if not evidence_ids:
            warnings.append("Insufficient verified abstract evidence; zero evidence records returned.")
        warnings.append("Model costs are unavailable; no actual cost was inferred. Evidence is abstract-level and requires later scientific review.")
        result = EvidenceGatheringResult(project_id=project_id, queries=plan.queries, providers_used=batch.providers_used,
            provider_counts=batch.provider_counts, raw_result_count=len(batch.results), deduplicated_count=len(unique),
            screened_count=screened_count, deeply_analyzed_count=deep_count,
            source_ids=[source.source_id for source in sources.values()], evidence_ids=evidence_ids,
            warnings=warnings, summary=f"Retrieved {len(batch.results)} results; selected {deep_count} papers; returned {len(evidence_ids)} verified evidence records.")
        events = [self._event(project_id, "SOURCE_ADDED", "Provider-verified source registered", {"source_id": source.source_id}, source.source_id)
                  for source in new_sources]
        events += [self._event(project_id, "EVIDENCE_ADDED", "Abstract-grounded claim registered",
                   {"evidence_id": evidence.evidence_id, "source_id": evidence.source_id}, evidence.evidence_id) for evidence in records]
        events.append(self._event(project_id, "EVIDENCE_GATHERING_COMPLETED", result.summary,
            {"source_ids": result.source_ids, "evidence_ids": result.evidence_ids, "raw_count": result.raw_result_count,
             "screened_count": screened_count, "deep_count": deep_count, "unsupported_claims": sum(w.startswith("Rejected unsupported") for w in warnings)}))
        # Source inserts precede their evidence links; all records and completion
        # audit are atomic. Recheck pause/runtime and concurrent source writes.
        def check():
            fresh = self._allowed(project_id)
            if fresh.sources != existing or fresh.evidence != known_evidence:
                raise EvidenceOutputError("Evidence/source state changed; rebuild the specialist context")
        self.ledger.add_many([*new_sources, *records, *events], check=check)
        return result
