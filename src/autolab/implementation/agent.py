"""Both independent roles use the official Omnigent CLI/server transport."""
import json
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.planner.service import OmnigentPlanner
from .models import ImplementationPlan, SourceBundle, ImplementationError


class OmnigentImplementer:
    def __init__(self, *, timeout_seconds=420):
        self.transport = OmnigentPlanner(timeout_seconds=timeout_seconds)

    async def _invoke(self, payload, schema):
        payload['output_schema'] = schema.model_json_schema()
        prompt = json.dumps(payload, allow_nan=False)
        if len(prompt) > 100000: raise ImplementationError('Implementation context exceeds bound')
        raw = await self.transport.invoke_agent(PROJECT_ROOT/'agents/implementer/implementer.yaml', prompt,
            project_id=payload['context']['experiment_spec']['project_id'], role='implementer')
        try: return schema.model_validate_json(raw)
        except ValueError: raise ImplementationError('Malformed Implementer output; no fallback or unbounded retry') from None

    async def plan(self, context, assignment, *, previous=None, review=None):
        return await self._invoke({'context': context, 'assignment': assignment,
            'previous_plan': previous.model_dump(mode='json') if previous else None,
            'review': review.model_dump(mode='json') if review else None,
            'instructions': 'PLAN ONLY, JSON only. Omit created_at. Exact assigned bindings. Copy objective, conditions=spec.independent_variables, baseline=spec.controls and input_resources=manifest.resources verbatim. expected_files MUST include experiment.py and test_experiment.py, optionally helpers.py, with no paths or other files. Do not include the framework-owned plan/spec/check/review JSON artifacts in expected_files. Components and mapping targets use filename.py:Class.method or filename.py:function format. Map every supplied requirement field path dynamically to an existing planned code component. Do not redesign science. Use metric component names from the framework adapter. Return blockers if contract impossible. Answer each review issue_index once using ACCEPT/REJECT/NEEDS_CLARIFICATION with concise evidence. REJECT is valid when supported; do not automatically obey reviewer overreach. No source code in this planning response.'}, ImplementationPlan)

    async def generate(self, context, plan, *, previous_files=None, review=None):
        return await self._invoke({'context': context, 'approved_implementation_plan': plan.model_dump(mode='json'),
            'previous_files': previous_files, 'review': review.model_dump(mode='json') if review else None,
            'instructions': 'Return SourceBundle JSON files only, exactly plan.expected_files. Implement Experiment(BaseExperiment) with setup(self,context), run(self,context), collect_results(self,context). Include experiment ID and spec fingerprint constants, resource ID/checksum constants and validate hashes in setup. Context is a dict with resources keyed by resource_id (parsed JSON), resource_hashes keyed by resource_id, experiment_id, experiment_version, seed. No raw file or network access. Framework smoke only calls setup and helpers on toy data; never run. Use only provided restricted Python profile. Plain zero-argument test_* functions with asserts, no unittest/pytest import. Generated tests must exercise helpers, controls, budgets, validation and reproducibility using tiny toy data. Framework-owned tests are independent. No print, eval, exec, open, shell, os, pathlib, external modules, reflection/dunder attributes, decorators or dynamic imports. Use math/json/statistics or random.Random(seed) if needed. No pass/TODO. Propagate input errors honestly. Implement every preregistered metric; no hard-coded outcomes. Run returns structured raw observations only; no scientific run is performed here. Preserve raw output schema from context and return records with experiment_id,experiment_version,observations,metadata. No changes to scientific variables, controls, criteria, sampling or approved conditions.'}, SourceBundle)


class OmnigentCodeAuditor:
    def __init__(self, *, timeout_seconds=420):
        self.transport = OmnigentPlanner(timeout_seconds=timeout_seconds)

    async def audit(self, context, assignment):
        payload = {'context': context, 'assignment': assignment, 'output_schema': s.ReviewRecord.model_json_schema(),
            'instructions': 'Return ONLY canonical ReviewRecord JSON. Omit created_at. Copy exact target and all assignment.metadata pins. Independent audit: assess scientific fidelity, hypothesis, all baselines/conditions, primary and secondary metric denominators, budgets, hashes/versions, splits/leakage, fairness, seeds, failures/missing samples, parsing bias, target leakage, reproducibility, forbidden access, scientific drift and hard-coded outcomes. Agent agreement does not prove correctness. Deterministic failures prevent readiness even if you PASS. PASS/REVISE/REJECT/BLOCK supported; legitimate defects must never be forced to PASS. Every material issue must have severity, component, requirement, problem, impact, correction. Reassess Implementer ACCEPT/REJECT/NEEDS_CLARIFICATION with objective evidence; you may accept a sound rebuttal or maintain a justified concern. Do not require Phase 10 experiment execution or scientific results. No hidden reasoning.'}
        payload['binding_rules'] = 'Copy every assignment field literally, including target_type=implementations and target_version=1. metadata MUST equal assignment.metadata with no omitted/renamed/added keys. Place audit comments in issues, questions or recommendations, never in metadata. This enforces exact code/scientific hash provenance and does not influence your verdict.'
        prompt = json.dumps(payload, allow_nan=False)
        if len(prompt) > 150000: raise ImplementationError('Code Auditor context exceeds bound')
        raw = await self.transport.invoke_agent(PROJECT_ROOT/'agents/code_auditor/code_auditor.yaml', prompt,
            project_id=assignment['project_id'], role='code_auditor')
        try: return s.ReviewRecord.model_validate_json(raw)
        except ValueError: raise ImplementationError('Malformed Code Auditor output; bounded failure') from None
