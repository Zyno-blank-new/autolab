"""Control-plane read models; canonical scientific records remain in SQLite."""
from datetime import datetime
from enum import StrEnum

from pydantic import Field
from autolab import schemas as s


class ControlStage(StrEnum):
    INITIALIZED = "INITIALIZED"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    HYPOTHESIS_FORMATION = "HYPOTHESIS_FORMATION"
    HYPOTHESIS_REVIEW = "HYPOTHESIS_REVIEW"
    EXPERIMENT_DESIGN = "EXPERIMENT_DESIGN"
    EXPERIMENT_REVIEW = "EXPERIMENT_REVIEW"
    AWAITING_HUMAN_APPROVAL = "AWAITING_HUMAN_APPROVAL"
    RESOURCE_PREPARATION = "RESOURCE_PREPARATION"
    READINESS_REVIEW = "READINESS_REVIEW"
    IMPLEMENTATION = "IMPLEMENTATION"
    CODE_REVIEW = "CODE_REVIEW"
    READY_TO_RUN = "READY_TO_RUN"
    RUNNING = "RUNNING"
    ANALYSIS = "ANALYSIS"
    ANALYSIS_REVIEW = "ANALYSIS_REVIEW"
    ADAPTIVE_DECISION = "ADAPTIVE_DECISION"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    PAUSED = "PAUSED"


class ValidationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    NEEDS_HUMAN_APPROVAL = "NEEDS_HUMAN_APPROVAL"
    BUDGET_BLOCKED = "BUDGET_BLOCKED"
    TIME_BLOCKED = "TIME_BLOCKED"


class ValidationResult(s.Record):
    status: ValidationStatus
    reasons: list[str] = Field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.status == ValidationStatus.VALID


class ProjectSnapshot(s.Record):
    charter: s.ResearchCharter
    authorized_scope: s.ResearchCharter | None = None
    sources: list[s.SourceRecord] = Field(default_factory=list)
    evidence: list[s.EvidenceRecord] = Field(default_factory=list)
    hypotheses: list[s.Hypothesis] = Field(default_factory=list)
    reviews: list[s.ReviewRecord] = Field(default_factory=list)
    candidates: list[s.ExperimentCandidate] = Field(default_factory=list)
    experiments: list[s.ExperimentSpec] = Field(default_factory=list)
    resources: list[s.ResourceRecord] = Field(default_factory=list)
    readiness: list[s.ReadinessReport] = Field(default_factory=list)
    implementations: list[s.ImplementationRecord] = Field(default_factory=list)
    runs: list[s.ExperimentRun] = Field(default_factory=list)
    metrics: list[s.MetricRecord] = Field(default_factory=list)
    analyses: list[s.ScientificAnalysis] = Field(default_factory=list)
    decisions: list[s.NextDecision] = Field(default_factory=list)
    costs: list[s.CostRecord] = Field(default_factory=list)
    events: list[s.EventRecord] = Field(default_factory=list)


class BudgetState(s.Record):
    initial_budget_usd: s.Nonnegative
    estimated_spent_usd: s.Nonnegative
    actual_spent_usd: s.Nonnegative
    remaining_budget_usd: s.Nonnegative
    unknown_actual_cost_ids: list[str] = Field(default_factory=list)


class TimeState(s.Record):
    created_at: datetime
    elapsed_minutes: s.Nonnegative
    remaining_minutes: s.Nonnegative | None


class ApprovalScope(s.Record):
    """Payload of HUMAN_APPROVED; only a trusted human event grants authority."""
    experiment_id: s.Text
    experiment_version: s.Version = 1
    approved_actions: list[s.PlannerAction]
    max_cost_usd: s.Nonnegative
    max_runtime_minutes: s.Nonnegative
    implementation_id: str | None = None
    decision_id: str | None = None
    assessment_id: str | None = None
    assessment_version: s.Version | None = None
    assessment_fingerprint: str | None = None
    spec_fingerprint: str | None = None
    packet_id: str | None = None
    note: str | None = None
    acknowledged_unknowns: bool = False


class ContextLimits(s.Record):
    recent_decisions: int = Field(default=5, ge=1, le=50)
    recent_events: int = Field(default=8, ge=1, le=50)
    records_per_kind: int = Field(default=6, ge=1, le=50)
    summary_chars: int = Field(default=320, ge=40, le=2000)
    max_json_chars: int = Field(default=24000, ge=4000, le=100000)


class PlannerContext(s.Record):
    charter: s.ResearchCharter
    control_state: ControlStage
    project_status: s.ProjectStatus
    budget: BudgetState
    time: TimeState
    counts: dict[str, int]
    summaries: dict[str, list[s.JSON]]
    current_records: s.JSON
    available_roles: list[str]
    available_actions: list[s.PlannerAction]
    action_targets: dict[str, list[str]]
    omitted_records: dict[str, int]
    charter_fingerprint: str


class RoutingDecision(s.Record):
    decision_id: str
    action: s.PlannerAction
    target_role: str | None
    reason: str
    context_requirements: list[str]
    control_state: ControlStage
