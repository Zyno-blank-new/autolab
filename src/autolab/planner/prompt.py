"""Structured input for the existing Omnigent planner; no prose history dump."""
import json
from autolab.orchestration.models import PlannerContext
from autolab.schemas import NextDecision


def planner_request(context: PlannerContext, decision_id: str, feedback: dict | None = None) -> str:
    # Round names are visible lineage labels, while required_context_ids binds
    # canonical records. Advertise this distinction without relaxing validation.
    identifiers = {context.charter.project_id}
    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {'id', 'source_id', 'event_id', 'decision_id', 'hypothesis_id',
                           'experiment_id', 'run_id', 'analysis_id', 'metric_id',
                           'implementation_id', 'plan_id'} and isinstance(child, str):
                    identifiers.add(child)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(context.summaries)
    collect(context.current_records)
    scope = context.current_records.get('authorized_research_scope')
    if scope:
        identifiers.add(scope['project_id'])
    return json.dumps({
        "planner_context": context.model_dump(mode="json"),
        "output_schema": NextDecision.model_json_schema(),
        "assigned_identity": {"decision_id": decision_id, "project_id": context.charter.project_id},
        "allowed_visible_context_ids": sorted(identifiers),
        "specialist_capabilities": {
            "evidence": "Bounded scholarly retrieval and provenance-grounded abstract extraction; after a completed run, bounded existing-artifact inspection. No general mathematical proof checker, new measurement, or experiment execution.",
            "preparation": "PREPARE_RESOURCES targets preparation to create/register resources or resume an existing approved plan. A preparation plan alone is not a prepared resource manifest.",
            "readiness": "PREPARE_RESOURCES may target readiness only when current_records.resource_manifest exists with registered resources. Readiness independently audits those prepared resources; it cannot create them or resume preparation."},
        "instructions": "Choose one legal action. Return strict JSON only. Omit created_at; local code timestamps acceptance. required_context_ids must use actual supplied canonical record IDs; round names are lineage labels and may appear in the reason, not required_context_ids. Scientific inference must be labeled as inference, not fabricated publication evidence.",
        "repair": feedback,
    }, allow_nan=False)
