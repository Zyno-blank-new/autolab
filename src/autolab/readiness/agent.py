import json
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.planner.service import OmnigentPlanner
from autolab.preparation.models import PreparationError


class OmnigentReadinessAuditor:
    def __init__(self, *, timeout_seconds=360):
        self.transport=OmnigentPlanner(timeout_seconds=timeout_seconds)

    async def audit(self, context, assignment):
        payload={'audit_context':context,'assigned_report':assignment,'output_schema':s.ReadinessReport.model_json_schema(),
            'instructions':'Return ONLY canonical ReadinessReport. Omit created_at. Evaluate every critical PRE-IMPLEMENTATION resource requirement across all four Boolean gates. Experiment code, runnable tool adapters and code tests belong to Phase 9; do not require them as resource artifacts, but do require complete and scientifically faithful data/configuration contracts. metadata.semantic_findings must be a nonempty list of concise objects with gate, resource_ids, finding, evidence. metadata.issues is a list of specific fixable or blocking problems with resource_ids. Reference ONLY supplied current resource IDs/versions. Report warnings for limits; do not call a mechanics-only fixture a scientifically powered test. PASS requires all gates true and no failed_checks. Do not override deterministic failure. No code or experiment results.'}
        prompt=json.dumps(payload,allow_nan=False)
        if len(prompt)>65000: raise PreparationError('Readiness request exceeds bounded audit context')
        raw=await self.transport.invoke_agent(PROJECT_ROOT/'agents/readiness/readiness.yaml',prompt,
            project_id=assignment['project_id'],role='readiness')
        try: return s.ReadinessReport.model_validate_json(raw)
        except ValueError: raise PreparationError('Readiness Auditor returned malformed report') from None
