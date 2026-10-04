"""Batched Hypothesis Scientist and Scientific Critic through Omnigent."""
import json
from pydantic import ValidationError
from autolab.config import PROJECT_ROOT
from autolab.planner.service import OmnigentPlanner
from .models import HypothesisBatch, ReviewBatch, RevisionBatch, HypothesisOutputError
from .context import critic_packet


class OmnigentHypothesisAgent:
    def __init__(self, *, timeout_seconds=240, model=None):
        self.transport = OmnigentPlanner(timeout_seconds=timeout_seconds, model=model)

    @property
    def calls(self):
        return self.transport.calls

    async def _request(self, context, stage, schema, **data):
        payload = {"stage": stage, "hypothesis_context": context.model_dump(mode="json"),
                   "output_schema": schema.model_json_schema(), **data}
        prompt = json.dumps(payload, allow_nan=False)
        if len(prompt) > 100000:
            raise HypothesisOutputError("Hypothesis request exceeds the bounded model context")
        raw = await self.transport.invoke_agent(PROJECT_ROOT / "agents/hypothesis/hypothesis.yaml",
            prompt, project_id=context.charter.project_id, role="hypothesis")
        try:
            return schema.model_validate_json(raw)
        except ValidationError:
            raise HypothesisOutputError(f"Hypothesis {stage} returned malformed structured output") from None

    async def generate(self, context, assignments):
        return await self._request(context, "generation", HypothesisBatch, assigned_candidates=assignments,
            instructions="Return exactly the assigned number of distinct candidates, or an empty list plus insufficient_basis. Omit created_at. Use assigned IDs/versions and PROPOSED status. Each rationale starts AGENT-GENERATED HYPOTHESIS and contains SUPPORTED BY EVIDENCE: and SCIENTIFIC INFERENCE / PROPOSED EXPLANATION: sections. Uncited hypotheses must say LOW-CONFIDENCE. All three advisory scores required.")

    async def revise(self, context, hypotheses, reviews, assignments):
        return await self._request(context, "revision", RevisionBatch, assigned_candidates=assignments,
            hypotheses=[h.model_dump(mode="json") for h in hypotheses], reviews=[r.model_dump(mode="json") for r in reviews],
            instructions="Only one revision/rebuttal round exists. Return every assigned candidate with REFINED status and the assigned next version. Preserve origin/evidence/inference labels. Respond to EACH issue by zero-based issue_index and review_id: ACCEPT, REBUT, or CLARIFY with a reason and real evidence_ids. Do not automatically accept critique. Preserve defensible claims with a reasoned rebuttal. Omit created_at.")

    async def refine(self, context, hypothesis, assignments):
        return await self._request(context, 'post_result_refinement', RevisionBatch,
            assigned_candidates=assignments, original_hypothesis=hypothesis.model_dump(mode='json'),
            instructions='Refine exactly the assigned hypothesis/version in light of reviewed_result and Planner reason. REFINED status; retain origin/evidence/inference labels and uncertainty. responses=[] because this is a new PI scientific request, not a response to a fabricated Critic review. Preserve history and provide a changed falsifiable prediction; do not merely paraphrase. Omit created_at.')


class OmnigentScientificCritic:
    def __init__(self, *, timeout_seconds=240, model=None):
        self.transport = OmnigentPlanner(timeout_seconds=timeout_seconds, model=model)

    @property
    def calls(self):
        return self.transport.calls

    async def review_analysis(self, context, analysis, assignment, *, findings=None, responses=None):
        from autolab.analysis.models import AnalysisError
        payload = {"review_mode": "analysis", "stage": "final_review" if responses is not None else "initial_review",
            "scientific_context": context, "analysis": analysis.model_dump(mode="json"),
            "assigned_review": assignment, "deterministic_guard_findings": findings or [],
            "responses": [r.model_dump(mode="json") for r in responses or []],
            "output_schema": ReviewBatch.model_json_schema(),
            "instructions": "Return exactly one canonical independent ReviewRecord: review_type=analysis, target_type=analyses, reviewer_role=critic, exact assigned ID/project/target/version. PASS/REVISE/REJECT only. At most eight issues, five questions/recommendations. Material issues require problem/severity/section/evidence_ids/why_it_matters/resolution. Non-PASS requires concrete issues. Examine hypothesis discrimination, numeric direction/criteria, failures/coverage, all secondary outcomes, confounds, sample adequacy, exploratory labels, scope and statistics. Do not force PASS. Never mutate evidence, accept hypotheses or execute actions. Omit created_at. Final review ends discussion even if disagreement remains."}
        prompt = json.dumps(payload, allow_nan=False)
        if len(prompt) > 90000: raise AnalysisError("Analysis Critic context bound exceeded")
        raw = await self.transport.invoke_agent(PROJECT_ROOT / "agents/critic/critic.yaml",
            prompt, project_id=context['charter']['project_id'], role="critic")
        if len(raw)>30000: raise AnalysisError("Critic response bound exceeded")
        try: return ReviewBatch.model_validate_json(raw)
        except ValidationError: raise AnalysisError("Malformed Scientific Critic output") from None

    async def review_experiments(self, context, candidates, assignments, *, all_candidates=None, responses=None):
        from autolab.experiment_design.models import ExperimentDesignError
        from autolab.experiment_design.context import candidate_summary
        payload = {"review_mode": "experiment_design", "stage": "final_review" if responses is not None else "initial_review",
            "output_schema": ReviewBatch.model_json_schema(), "assigned_reviews": assignments,
            "experiment_design_context": context.model_dump(mode="json"),
            "candidates": [c.model_dump(mode="json") for c in candidates],
            "candidate_comparison": [candidate_summary(c) for c in all_candidates or candidates],
            "structured_criteria_semantics": "The selected hypothesis and success criterion must agree. For a hypothesis predicting that clipping harms MAE, a lower-MAE comparison can use control=clipped and intervention=baseline; the condition names and measured metric remain unchanged. A generic clipping-benefit criterion does not evaluate a harm hypothesis. Do not treat a reviewable mismatch as a future analysis workaround.",
            "responses": [r.model_dump(mode="json") for r in responses or []],
            "instructions": "Return one canonical independent ReviewRecord per assigned candidate. review_type=experiment, target_type=experiment_candidates, reviewer_role=critic. Exact assigned IDs/projects/target versions. At most 8 issues, 5 questions, 5 recommendations. Each issue has problem, why_it_matters, resolution, evidence_ids (supplied IDs only). Non-PASS requires concrete issues. Omit created_at. PASS means scientifically interpretable proposal, not resource readiness or approved spending. Assess null interpretation, minimum informative design, redundant alternatives, leakage and control fairness. If final review, reassess ACCEPT/REBUT/CLARIFY honestly; unresolved issues return to PI without another revision."}
        prompt = json.dumps(payload, allow_nan=False)
        if len(prompt) > 100000:
            raise ExperimentDesignError("Experiment Critic request exceeds context bound")
        raw = await self.transport.invoke_agent(PROJECT_ROOT / "agents/critic/critic.yaml",
            prompt, project_id=context.charter.project_id, role="critic")
        try:
            return ReviewBatch.model_validate_json(raw)
        except ValidationError:
            raise ExperimentDesignError("Scientific Critic experiment review returned malformed structured output") from None

    async def review(self, context, hypotheses, assignments, *, all_candidates=None, responses=None):
        payload = {"stage": "final_review" if responses is not None else "initial_review",
            "output_schema": ReviewBatch.model_json_schema(), "assigned_reviews": assignments,
            **critic_packet(context, hypotheses, all_candidates=all_candidates, responses=responses),
            "instructions": "Return canonical reviews, one independent verdict per assigned hypothesis. review_type= hypothesis, target_type=hypotheses, reviewer_role=critic. Use exact target versions/IDs and review IDs. At most 8 issues, 5 questions, 5 recommendations per target. Each issue has problem, why_it_matters, resolution, evidence_ids (only supplied IDs). Non-PASS requires issues. Omit created_at. This is the final check when responses are supplied; unresolved REVISE returns to Planner, never another revision."}
        prompt = json.dumps(payload, allow_nan=False)
        if len(prompt) > 100000:
            raise HypothesisOutputError("Critic request exceeds the bounded model context")
        raw = await self.transport.invoke_agent(PROJECT_ROOT / "agents/critic/critic.yaml",
            prompt, project_id=context.charter.project_id, role="critic")
        try:
            return ReviewBatch.model_validate_json(raw)
        except ValidationError:
            raise HypothesisOutputError("Scientific Critic returned malformed structured output") from None
