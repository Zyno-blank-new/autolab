"""Evidence reasoning via the same supported Omnigent transport as Planner."""
import json
from pydantic import ValidationError
from autolab.config import PROJECT_ROOT
from autolab.planner.service import OmnigentPlanner
from .models import QueryPlan, ScreeningResult, ExtractionResult
from .screening import EvidenceOutputError


class OmnigentEvidenceAgent:
    def __init__(self, *, timeout_seconds=180, model=None):
        self.transport = OmnigentPlanner(timeout_seconds=timeout_seconds, model=model)

    @property
    def calls(self):
        return self.transport.calls

    async def _request(self, charter, stage, schema, **data):
        prompt = json.dumps({"stage": stage, "research_charter": charter.model_dump(mode="json"),
                             "output_schema": schema.model_json_schema(), **data}, allow_nan=False)
        raw = await self.transport.invoke_agent(PROJECT_ROOT / "agents/evidence/evidence.yaml", prompt,
                                                 project_id=charter.project_id, role="evidence")
        try:
            return schema.model_validate_json(raw)
        except ValidationError:
            raise EvidenceOutputError(f"Evidence {stage} output does not match its structured contract") from None

    async def generate_queries(self, charter, query_count):
        plan = await self._request(charter, "query_generation", QueryPlan, query_count=query_count,
                                   instructions=f"Generate exactly {query_count} short scholarly search queries. Use provider-compatible AND/OR keywords or phrases, no URLs. Generalize from this charter.")
        if len(plan.queries) != query_count:
            raise EvidenceOutputError("Evidence query count differs from configured bound")
        return plan

    async def generate_adaptive_queries(self, charter, query_count, context):
        plan = await self._request(charter, 'adaptive_query_generation', QueryPlan, query_count=query_count,
            adaptive_context=context,
            instructions=f'If Planner requests inspection of existing run observations/provenance, choose inspect_existing_result=true and queries=[]; this uses deterministic original-artifact inspection, without literature retrieval or new experiments. Otherwise generate exactly {query_count} short scholarly queries addressing the evidence gap and reviewed-result limitation. Avoid blind retrieval of known source IDs/titles; preserve contradictions. No URLs.')
        if len(plan.queries) != (0 if plan.inspect_existing_result else query_count):
            raise EvidenceOutputError('Adaptive evidence query count differs from configured bound')
        return plan

    async def screen(self, charter, papers):
        return await self._request(charter, "relevance_screening", ScreeningResult, papers=papers,
            instructions="Score every supplied candidate exactly once. Role describes relation to the research question. Preserve relevant contradictory and methodological work. Relevance is not truth.")

    async def extract(self, charter, papers):
        return await self._request(charter, "evidence_extraction", ExtractionResult, papers=papers,
            instructions="Extract at most two useful claims per paper, at most ten total. Zero claims is valid when unsupported. Cite candidate_id only. supporting_text must be an exact contiguous passage copied from the supplied abstract; location must be abstract. Claim must be entailed by that passage. Qualify paper-reported and abstract-only findings; no new hypotheses or invented citations.")
