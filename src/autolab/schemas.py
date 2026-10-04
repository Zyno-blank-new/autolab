"""Canonical scientific records. Labels express assessments, not statistical proof."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Score = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Version = Annotated[int, Field(ge=1, strict=True)]
JSON = dict[str, JsonValue]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"


class HypothesisStatus(StrEnum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REFINED = "REFINED"


class ExperimentStatus(StrEnum):
    PROPOSED = "PROPOSED"
    SELECTED = "SELECTED"
    PREREGISTERED = "PREREGISTERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class ReviewVerdict(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    REJECT = "REJECT"
    BLOCK = "BLOCK"


class ReadinessVerdict(StrEnum):
    PASS = "PASS"
    REPAIR = "REPAIR"
    BLOCK = "BLOCK"


class HypothesisAssessment(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class PlannerAction(StrEnum):
    GATHER_EVIDENCE = "GATHER_EVIDENCE"
    GENERATE_HYPOTHESES = "GENERATE_HYPOTHESES"
    REFINE_HYPOTHESIS = "REFINE_HYPOTHESIS"
    DESIGN_EXPERIMENT = "DESIGN_EXPERIMENT"
    SELECT_EXPERIMENT = "SELECT_EXPERIMENT"
    PREPARE_RESOURCES = "PREPARE_RESOURCES"
    IMPLEMENT_EXPERIMENT = "IMPLEMENT_EXPERIMENT"
    RUN_EXPERIMENT = "RUN_EXPERIMENT"
    ANALYZE_RESULT = "ANALYZE_RESULT"
    RUN_FOLLOWUP = "RUN_FOLLOWUP"
    COLLECT_MORE_DATA = "COLLECT_MORE_DATA"
    REJECT_HYPOTHESIS = "REJECT_HYPOTHESIS"
    ACCEPT_HYPOTHESIS = "ACCEPT_HYPOTHESIS"
    REQUEST_HUMAN_APPROVAL = "REQUEST_HUMAN_APPROVAL"
    STOP = "STOP"


class Record(BaseModel):
    # Freezing fields prevents accidental reassignment. SQLite also rejects
    # overwrites. Nested containers are revalidated when saved.
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def normalize_datetimes(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Timestamps must include a timezone.")
            return value.astimezone(timezone.utc)
        return value


class TimedRecord(Record):
    created_at: datetime = Field(default_factory=utc_now)


class ResearchCharter(TimedRecord):
    project_id: Text
    title: Text
    research_question: Text
    objective: Text
    primary_outcome: Text
    success_criteria: JSON = Field(default_factory=dict)
    constraints: JSON = Field(default_factory=dict)
    budget_usd: Nonnegative = 0
    max_runtime_minutes: Nonnegative = 0
    stop_conditions: list[str] = Field(default_factory=list)
    status: ProjectStatus = ProjectStatus.ACTIVE


class SourceRecord(Record):
    source_id: Text
    project_id: Text
    title: Text
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=0, le=9999)
    doi: str | None = None
    url: str | None = None
    provider: str | None = None
    abstract: str | None = None
    metadata: JSON = Field(default_factory=dict)
    retrieved_at: datetime = Field(default_factory=utc_now)


class EvidenceRecord(TimedRecord):
    evidence_id: Text
    project_id: Text
    source_id: Text
    claim: Text
    supporting_text: str = ""
    location: str | None = None
    confidence: Score = 0
    tags: list[str] = Field(default_factory=list)


class Hypothesis(TimedRecord):
    hypothesis_id: Text
    project_id: Text
    statement: Text
    rationale: str = ""
    supporting_evidence_ids: list[Text] = Field(default_factory=list)
    contradicting_evidence_ids: list[Text] = Field(default_factory=list)
    falsifiable_prediction: Text
    novelty_score: Score | None = None
    testability_score: Score | None = None
    scientific_value_score: Score | None = None
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    version: Version = 1

    @model_validator(mode="after")
    def distinct_evidence(self):
        for ids in (self.supporting_evidence_ids, self.contradicting_evidence_ids):
            if len(ids) != len(set(ids)):
                raise ValueError("Evidence references must be unique within each list.")
        if set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids):
            raise ValueError("Evidence cannot both support and contradict the same hypothesis version.")
        return self


class ReviewRecord(TimedRecord):
    review_id: Text
    project_id: Text
    review_type: Text
    target_type: Text
    target_id: Text
    target_version: Version = 1
    verdict: ReviewVerdict
    severity: str = "info"
    issues: list[JSON] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    reviewer_role: Text
    metadata: JSON = Field(default_factory=dict)


class ExperimentCandidate(TimedRecord):
    candidate_id: Text
    project_id: Text
    hypothesis_id: Text
    hypothesis_version: Version = 1
    title: Text
    objective: Text
    approach: Text
    expected_information_gain: Score | None = None
    estimated_cost_usd: Nonnegative | None = 0
    estimated_runtime_minutes: Nonnegative | None = 0
    feasibility_score: Score | None = None
    major_risks: list[str] = Field(default_factory=list)
    status: ExperimentStatus = ExperimentStatus.PROPOSED
    # Scientific proposal fields use ExperimentSpec's field names. Phase 6
    # validates these before review; legacy candidates may have empty designs.
    design: JSON = Field(default_factory=dict)
    version: Version = 1


class ExperimentSpec(TimedRecord):
    experiment_id: Text
    project_id: Text
    hypothesis_id: Text
    hypothesis_version: Version = 1
    title: Text
    objective: Text
    experiment_type: Text
    independent_variables: JSON = Field(default_factory=dict)
    dependent_variables: JSON = Field(default_factory=dict)
    controls: JSON = Field(default_factory=dict)
    dataset_requirements: JSON = Field(default_factory=dict)
    required_resources: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    primary_metric: Text
    secondary_metrics: list[str] = Field(default_factory=list)
    success_criteria: JSON = Field(default_factory=dict)
    falsification_criteria: JSON = Field(default_factory=dict)
    potential_confounders: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    estimated_cost_usd: Nonnegative | None = 0
    estimated_runtime_minutes: Nonnegative | None = 0
    expected_information_gain: Score | None = None
    version: Version = 1
    status: ExperimentStatus = ExperimentStatus.PREREGISTERED


class ExperimentLinked(TimedRecord):
    project_id: Text
    experiment_id: Text
    experiment_version: Version = 1


class ResourceRecord(ExperimentLinked):
    resource_id: Text
    resource_type: Text
    purpose: Text
    path_or_uri: Text
    source: str | None = None
    version: str = "1"
    checksum: str | None = None
    metadata: JSON = Field(default_factory=dict)
    status: str = "REGISTERED"


class ReadinessReport(ExperimentLinked):
    # Additive audit provenance; legacy records still parse but lack current pins.
    metadata: JSON = Field(default_factory=dict)
    readiness_id: Text
    resource_readiness: bool
    technical_readiness: bool
    scientific_readiness: bool
    quality_readiness: bool
    failed_checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    verdict: ReadinessVerdict


class ImplementationRecord(ExperimentLinked):
    implementation_id: Text
    code_path: Text
    implementation_plan: list[str] = Field(default_factory=list)
    code_version: Text
    status: str = "REGISTERED"
    metadata: JSON = Field(default_factory=dict)


class ExperimentRun(Record):
    run_id: Text
    project_id: Text
    experiment_id: Text
    experiment_version: Version = 1
    implementation_id: Text
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    status: RunStatus = RunStatus.PENDING
    random_seed: int | None = None
    environment_metadata: JSON = Field(default_factory=dict)
    input_manifest: JSON = Field(default_factory=dict)
    output_manifest: JSON = Field(default_factory=dict)
    error_message: str | None = None
    cost_usd: Nonnegative | None = 0

    @model_validator(mode="after")
    def completion_follows_start(self):
        if self.completed_at and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at.")
        return self


class MetricRecord(ExperimentLinked):
    metric_id: Text
    run_id: Text
    metric_name: Text
    metric_value: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    unit: str | None = None
    metadata: JSON = Field(default_factory=dict)


class ScientificAnalysis(ExperimentLinked):
    analysis_id: Text
    version: Version = 1
    hypothesis_id: str | None = None
    hypothesis_version: Version = 1
    metric_ids: list[Text] = Field(default_factory=list)
    evidence_pins: JSON = Field(default_factory=dict)
    criteria_evaluation: JSON = Field(default_factory=dict)
    confounders: list[JSON] = Field(default_factory=list)
    claims: list[JSON] = Field(default_factory=list)
    causal_scope: str = "Unspecified"
    generalization_scope: str = "Unspecified"
    run_id: Text
    hypothesis_assessment: HypothesisAssessment
    interpretation: Text
    key_findings: list[str] = Field(default_factory=list)
    unexpected_findings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    remaining_uncertainties: list[str] = Field(default_factory=list)
    confidence: Score = 0
    recommended_followup: list[str] = Field(default_factory=list)


class NextDecision(TimedRecord):
    decision_id: Text
    project_id: Text
    action: PlannerAction
    target_agent: str | None = None
    reason: Text
    expected_information_gain: Score | None = None
    goal_alignment: Score | None = None
    required_context_ids: list[Text] = Field(default_factory=list)
    remaining_budget_usd: Nonnegative = 0


class CostRecord(TimedRecord):
    cost_id: Text
    project_id: Text
    experiment_id: Text | None = None
    experiment_version: Version = 1
    category: Text
    estimated_usd: Nonnegative = 0
    actual_usd: Nonnegative | None = 0
    metadata: JSON = Field(default_factory=dict)


class EventRecord(TimedRecord):
    event_id: Text
    project_id: Text
    event_type: Text
    actor: Text
    target_type: str | None = None
    target_id: str | None = None
    summary: Text
    payload: JSON = Field(default_factory=dict)

    @model_validator(mode="after")
    def paired_target(self):
        if (self.target_type is None) != (self.target_id is None):
            raise ValueError("target_type and target_id must be supplied together.")
        return self
