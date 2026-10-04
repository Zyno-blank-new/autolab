"""The registered Experimental Scientist uses the proven Omnigent transport."""
import json
from pydantic import ValidationError
from autolab.config import PROJECT_ROOT
from autolab import schemas as s
from autolab.planner.service import OmnigentPlanner
from .models import CandidateBatch, CandidateRevision, ExperimentDesignError
from .validation import SPEC_FIELDS, EXTRA_DESIGN_FIELDS, REQUIRED_DESIGN_FIELDS, proposal_output_schema


class OmnigentExperimentDesigner:
    def __init__(self, *, timeout_seconds=300, model=None):
        self.transport = OmnigentPlanner(timeout_seconds=timeout_seconds, model=model)

    @property
    def calls(self):
        return self.transport.calls

    async def _request(self, context, stage, schema, **data):
        payload = {"stage": stage, "experiment_design_context": context.model_dump(mode="json"),
            "output_schema": proposal_output_schema(schema),
            "design_field_schema": {k: v for k, v in s.ExperimentSpec.model_json_schema()["properties"].items() if k in SPEC_FIELDS},
            "allowed_design_fields": sorted(SPEC_FIELDS | EXTRA_DESIGN_FIELDS),
            "required_design_fields": sorted(REQUIRED_DESIGN_FIELDS), **data}
        prompt = json.dumps(payload, allow_nan=False)
        if len(prompt) > 100000:
            raise ExperimentDesignError("Designer request exceeds context bound")
        raw = await self.transport.invoke_agent(PROJECT_ROOT / "agents/experiment_designer/experiment_designer.yaml",
            prompt, project_id=context.charter.project_id, role="experiment_designer")
        try:
            return schema.model_validate_json(raw)
        except ValidationError:
            raise ExperimentDesignError(f"Experiment Designer {stage} returned malformed structured output") from None

    async def generate(self, context, assignments):
        return await self._request(context, "experiment_design", CandidateBatch, assigned_candidates=assignments,
            instructions="Return exactly the assigned 2–3 scientifically distinct canonical candidates. Use assigned IDs/project/hypothesis/version and PROPOSED status. Omit created_at. Put structured scientific fields in design using supplied names. success_criteria/falsification_criteria are objects. expected_result_patterns is an object with exactly supported, contradicted, inconclusive strings. metric_rationale, sampling_strategy, inconclusive_criteria are strings. Lists contain nonempty strings. All required design fields need meaningful values. Use null cost/runtime if unknown, never false zero or precise invented API dollars. Explain sample adequacy as unresolved when no power assumptions exist. No results, code, or acquisition.")

    async def revise(self, context, candidates, reviews, assignments):
        return await self._request(context, "experiment_design_revision", CandidateRevision,
            assigned_candidates=assignments, candidates=[c.model_dump(mode="json") for c in candidates],
            reviews=[r.model_dump(mode="json") for r in reviews],
            instructions="One final revision/rebuttal round. Return every assigned candidate with stable candidate_id, next assigned version, same hypothesis/version, PROPOSED status. Preserve complete structured design. Respond once to EACH issue via review_id and zero-based issue_index, disposition ACCEPT/REBUT/CLARIFY, concise scientific reason, and real evidence_ids. Acceptance should repair the concern, defensible rebuttal is allowed. Omit created_at. No additional round will run.")
