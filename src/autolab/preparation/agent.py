"""Preparation reasons through the existing Omnigent transport; handlers act."""
import json
from autolab.config import PROJECT_ROOT
from autolab.planner.service import OmnigentPlanner
from .models import PreparationError, ResourcePreparationPlan


class OmnigentPreparationAgent:
    def __init__(self, *, timeout_seconds=360):
        self.transport=OmnigentPlanner(timeout_seconds=timeout_seconds)

    async def plan(self, context, assignment, *, previous=None, issues=None):
        payload={'preparation_context':context,'assigned_plan':assignment,
            'output_schema':ResourcePreparationPlan.model_json_schema(),
            'previous_plan':previous.model_dump(mode='json') if previous else None,
            'repair_issues':issues or [],
            'instructions':'Return ONLY the assigned ResourcePreparationPlan. Omit created_at. Map ALL exact spec.required_resources strings via spec_requirements. If unavailable or impossible without changing science, return blockers/user_input_required/material_changes, never pretend success; unresolved handler parameters may be empty ONLY when the whole plan is BLOCKED or needs user input. Define acceptance before creation. Each handler is data only. synthetic parameters: {data: JSON object or list of rows, specification: string, seed: integer or null, shuffle: boolean optional}. local: {path: approved catalog path}. transform: {parent_requirement, operation: project or split, fields OR seed/group_field/split_field/train_fraction}; dependencies explicit. download: operator-approved URL and pinned sha256 only. No executable code, commands, installs, results, model answers to experimental tasks, hidden credentials or self-approval. Costs/time null when unknown. Reuse existing resource catalog if spec requires existing data. Repair must respond to every zero-based issue_index via ACCEPT/REBUT/CLARIFY and cannot relax original acceptance criteria.'}
        prompt=json.dumps(payload,allow_nan=False)
        if len(prompt)>90000: raise PreparationError('Preparation context exceeds bound')
        raw=await self.transport.invoke_agent(PROJECT_ROOT/'agents/preparation/preparation.yaml',prompt,
            project_id=assignment['project_id'],role='preparation')
        try: return ResourcePreparationPlan.model_validate_json(raw)
        except ValueError: raise PreparationError('Preparation Agent returned malformed plan') from None
