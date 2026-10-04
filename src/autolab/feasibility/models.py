"""Typed payloads stored in existing EventRecord and CostRecord tables."""
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator
from autolab import schemas as s


class CapabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    REQUIRES_CREDENTIAL = "REQUIRES_CREDENTIAL"
    UNKNOWN = "UNKNOWN"


class FeasibilityStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    FEASIBLE_WITH_WARNINGS = "FEASIBLE_WITH_WARNINGS"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    BLOCKED = "BLOCKED"


class BudgetStatus(StrEnum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    POSSIBLY_WITHIN_BUDGET = "POSSIBLY_WITHIN_BUDGET"
    OVER_BUDGET = "OVER_BUDGET"
    UNKNOWN = "UNKNOWN"


class TimeStatus(StrEnum):
    WITHIN_TIME = "WITHIN_TIME"
    AT_RISK = "AT_RISK"
    OVER_TIME = "OVER_TIME"
    UNKNOWN = "UNKNOWN"


class Complexity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class HumanDecision(StrEnum):
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    REJECT = "REJECT"


class EstimateRange(s.Record):
    minimum: s.Nonnegative | None = None
    expected: s.Nonnegative | None = None
    maximum: s.Nonnegative | None = None

    @model_validator(mode="after")
    def ordered(self):
        values = [x for x in (self.minimum, self.expected, self.maximum) if x is not None]
        if values != sorted(values):
            raise ValueError("Estimate bounds must be ordered.")
        return self


class Capability(s.Record):
    capability_id: s.Text
    status: CapabilityStatus
    provider: str | None = None
    configuration_requirement: str | None = None
    credential_requirement: str | None = None  # Name only, never its value.
    cost_driver: str | None = None
    requires_capabilities: list[s.Text] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ResourceAccess(s.Record):
    requirement: s.Text
    status: CapabilityStatus = CapabilityStatus.UNKNOWN
    notes: list[str] = Field(default_factory=list)


class CostInput(s.Record):
    category: s.Text
    units: EstimateRange = Field(default_factory=EstimateRange)
    unit_price_usd: s.Nonnegative | None = None
    unit: s.Text = "configured unit"
    assumptions: list[s.Text] = Field(default_factory=list)
    confidence: s.Score | None = None


class CostCategory(s.Record):
    category: s.Text
    estimate_usd: EstimateRange
    assumptions: list[str]
    unknown_drivers: list[str]
    confidence: s.Score | None = None


class CostEstimate(s.Record):
    estimate_usd: EstimateRange
    categories: list[CostCategory]
    assumptions: list[str]
    unknown_cost_drivers: list[str]
    confidence: s.Score | None = None


class FeasibilityInputs(s.Record):
    capability_mapping: dict[str, list[s.Text]] = Field(default_factory=dict)
    resource_access: list[ResourceAccess] = Field(default_factory=list)
    costs: list[CostInput] = Field(default_factory=list)
    runtime_minutes: EstimateRange | None = None
    runtime_assumptions: list[s.Text] = Field(default_factory=list)
    unknown_runtime_drivers: list[s.Text] = Field(default_factory=list)
    credential_requirements: list[s.Text] = Field(default_factory=list)
    external_api_requirements: list[s.Text] = Field(default_factory=list)
    compute_requirements: list[s.Text] = Field(default_factory=list)
    storage_gb: EstimateRange | None = None
    implementation_complexity: Complexity = Complexity.UNKNOWN
    execution_risks: list[s.Text] = Field(default_factory=list)
    warnings: list[s.Text] = Field(default_factory=list)
    user_input_required: list[s.Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def unambiguous_resources(self):
        names = [r.requirement for r in self.resource_access]
        if len(set(names)) != len(names):
            raise ValueError("Resource access declarations must be unique.")
        if any(not ids or len(set(ids)) != len(ids) for ids in self.capability_mapping.values()):
            raise ValueError("Capability mappings must identify nonempty unique capabilities.")
        return self


class FeasibilityAssessment(s.TimedRecord):
    assessment_id: s.Text
    version: s.Version = 1
    project_id: s.Text
    experiment_id: s.Text
    experiment_version: s.Version
    spec_fingerprint: s.Text
    status: FeasibilityStatus
    required_capabilities: list[str]
    capabilities: list[Capability]
    available_capabilities: list[str]
    missing_capabilities: list[str]
    required_resources: list[str]
    resource_access: list[ResourceAccess]
    unresolved_resource_requirements: list[str]
    credential_requirements: list[str]
    external_api_requirements: list[str]
    compute_requirements: list[str]
    storage_gb: EstimateRange | None
    cost: CostEstimate
    runtime_minutes: EstimateRange
    runtime_assumptions: list[str]
    unknown_runtime_drivers: list[str]
    remaining_budget_usd: s.Nonnegative
    budget_status: BudgetStatus
    remaining_time_minutes: s.Nonnegative | None
    time_status: TimeStatus
    implementation_complexity: Complexity
    execution_risks: list[str]
    blockers: list[str]
    warnings: list[str]
    user_input_required: list[str]

    @property
    def has_unknown_estimates(self):
        return bool(self.cost.unknown_cost_drivers or self.cost.estimate_usd.maximum is None
                    or self.runtime_minutes.maximum is None or self.unknown_runtime_drivers)


class ApprovalPacket(s.TimedRecord):
    packet_id: s.Text
    project_id: s.Text
    experiment_id: s.Text
    experiment_version: s.Version
    assessment_id: s.Text
    assessment_version: s.Version
    spec_fingerprint: s.Text
    title: s.Text
    hypothesis_id: s.Text
    hypothesis_version: s.Version
    objective: s.Text
    primary_metric: s.Text
    selection_reason: str
    expected_information_gain: s.Score | None
    assessment: FeasibilityAssessment
    remaining_budget_usd: s.Nonnegative
    remaining_time_minutes: s.Nonnegative | None
    decision_id: str | None = None
    approval_options: list[HumanDecision] = Field(default_factory=lambda: list(HumanDecision))


class HumanResponse(s.TimedRecord):
    project_id: s.Text
    experiment_id: s.Text
    experiment_version: s.Version
    packet_id: s.Text
    assessment_id: s.Text
    assessment_version: s.Version
    decision: HumanDecision
    actor: Literal["human", "test-human"]
    note: str | None = None
