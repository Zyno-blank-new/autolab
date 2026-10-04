"""Bounded preparation contracts. Resources and readiness use canonical models."""
from typing import Literal
from pydantic import Field, model_validator
from autolab import schemas as s


class PreparationError(RuntimeError):
    pass


class AcceptanceCriteria(s.Record):
    required_fields: list[s.Text] = Field(default_factory=list, max_length=40)
    field_types: dict[str, Literal['string','number','integer','boolean','object','array']] = Field(default_factory=dict)
    min_samples: int = Field(default=0, ge=0, le=2000)
    unique_fields: list[s.Text] = Field(default_factory=list)
    condition_field: str | None = None
    required_conditions: list[s.Text] = Field(default_factory=list)
    min_per_condition: int = Field(default=1, ge=1)
    split_field: str | None = None
    split_group_fields: list[s.Text] = Field(default_factory=list)
    label_field: str | None = None
    forbidden_input_fields: list[s.Text] = Field(default_factory=list)
    input_fields: list[s.Text] = Field(default_factory=list)
    scientific: list[s.Text] = Field(min_length=1, max_length=16)
    technical: list[s.Text] = Field(min_length=1, max_length=16)
    provenance: list[s.Text] = Field(min_length=1, max_length=16)


class ResourceRequirement(s.Record):
    requirement_id: s.Text
    spec_requirements: list[s.Text] = Field(min_length=1)
    resource_type: s.Text
    modality: s.Text = 'structured'
    purpose: s.Text
    acquisition_mode: Literal['EXISTING','DOWNLOAD','GENERATE','SYNTHESIZE','TRANSFORM','DERIVE','USER_PROVIDED']
    expected_output: s.Text
    source: str | None = None
    source_uri: str | None = None
    required_capabilities: list[s.Text] = Field(min_length=1)
    credential_requirement: str | None = None
    steps: list[s.Text] = Field(min_length=1,max_length=12)
    criteria: AcceptanceCriteria
    dependencies: list[s.Text] = Field(default_factory=list)
    handler: Literal['local','download','synthetic','transform']
    # This is DATA, never Python, a shell command, executable or an eval expression.
    parameters: s.JSON = Field(default_factory=dict)
    estimated_cost_usd: s.Nonnegative | None = None
    estimated_runtime_minutes: s.Nonnegative | None = None


class IssueResponse(s.Record):
    issue_index: int = Field(ge=0)
    disposition: Literal['ACCEPT','REBUT','CLARIFY']
    reason: s.Text


class ResourcePreparationPlan(s.ExperimentLinked):
    plan_id: s.Text
    version: s.Version = 1
    spec_fingerprint: s.Text
    resource_requirements: list[ResourceRequirement] = Field(default_factory=list,max_length=12)
    warnings: list[s.Text] = Field(default_factory=list,max_length=16)
    blockers: list[s.Text] = Field(default_factory=list,max_length=16)
    user_input_required: list[s.Text] = Field(default_factory=list,max_length=16)
    material_changes: list[s.Text] = Field(default_factory=list,max_length=16)
    additional_risks: list[s.Text] = Field(default_factory=list,max_length=16)
    issue_responses: list[IssueResponse] = Field(default_factory=list,max_length=24)

    @model_validator(mode='after')
    def unique_requirements(self):
        ids=[r.requirement_id for r in self.resource_requirements]
        if len(ids)!=len(set(ids)): raise ValueError('Duplicate requirement IDs')
        return self


class ResourcePin(s.Record):
    requirement_id: s.Text
    resource_id: s.Text
    version: s.Text
    checksum: s.Text
    path: s.Text
    record_fingerprint: s.Text
    status: s.Text


class ResourceManifest(s.ExperimentLinked):
    manifest_id: s.Text
    plan_id: s.Text
    plan_version: s.Version
    spec_fingerprint: s.Text
    resources: list[ResourcePin] = Field(default_factory=list,max_length=12)
    validation_requirements: dict[str, AcceptanceCriteria]
    unresolved_warnings: list[str] = Field(default_factory=list)
    manifest_path: s.Text


class PreparationResult(s.Record):
    project_id: str
    experiment_id: str
    experiment_version: int
    status: Literal['PREPARED','PASS','REPAIR','BLOCK','NEEDS_USER_INPUT','NEEDS_REAPPROVAL']
    plan_id: str | None = None
    manifest_id: str | None = None
    resource_ids: list[str] = Field(default_factory=list)
    readiness_id: str | None = None
    repair_attempts: int = Field(default=0,ge=0,le=2)
    warnings: list[str] = Field(default_factory=list)
    summary: str
