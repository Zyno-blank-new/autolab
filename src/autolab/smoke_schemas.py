"""Compatibility contracts used only by the original smoke utilities."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class ResearchQuestion(Schema):
    question: str = Field(min_length=1)
    domain: str = ""
    objective: str = ""

class Hypothesis(Schema):
    id: str
    statement: str
    rationale: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)

class ExperimentSpec(Schema):
    id: str
    hypothesis_id: str
    experiment_type: str
    variables: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    metrics: list[str] = Field(default_factory=list)
    tool: str = "experiment_runner"
    success_criteria: str = ""

class ExperimentResult(Schema):
    experiment_id: str
    status: Literal["success", "error"]
    metrics: dict[str, float] = Field(default_factory=dict)
    observations: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

class ScientificAnalysis(Schema):
    experiment_id: str
    interpretation: str
    supports_hypothesis: bool | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)

Action = Literal[
    "gather_evidence", "generate_hypothesis", "refine_hypothesis",
    "design_experiment", "run_experiment", "analyze_result",
    "run_followup_experiment", "reject_hypothesis", "accept_hypothesis",
    "collect_more_data", "stop",
]

class NextDecision(Schema):
    action: Action
    reason: str = Field(min_length=1)
    next_question: str | None = None
    target_agent: str | None = None
