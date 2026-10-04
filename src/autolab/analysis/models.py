"""Bounded interpretation envelopes around canonical scientific records."""
from typing import Literal
from pydantic import Field
from autolab import schemas as s
from autolab.hypotheses.models import CritiqueResponse

class AnalysisError(RuntimeError):
    pass

class ResultSummary(s.Record):
    run_id: str
    project_id: str
    experiment_id: str
    experiment_version: int
    hypothesis_id: str
    hypothesis_version: int
    pins: s.JSON
    available_evidence_ids: list[str]
    conditions: list[s.JSON]
    metrics: list[s.JSON]
    differences: list[s.JSON]
    criteria: s.JSON
    warnings: list[str]
    limitations: list[str]
    raw_artifact: s.JSON
    representative_observations: list[s.JSON]
    implementation_validation: s.JSON
    usage: s.JSON
    actual_cost_usd: float | None
    actual_cost_status: str
    statistics: Literal['Descriptive only'] = 'Descriptive only'

class AnalysisOutput(s.Record):
    analysis: s.ScientificAnalysis
    responses: list[CritiqueResponse] = Field(default_factory=list, max_length=8)

class AnalysisResult(s.Record):
    analysis_id: str
    version: int
    review_ids: list[str]
    revision_rounds: int
    verdict: str | None
    planner_control: bool = True
    phase12_executed: Literal[False] = False
