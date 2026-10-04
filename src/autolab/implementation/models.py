"""Bounded agent outputs; canonical implementation/review records remain shared."""
from typing import Literal
from pydantic import Field
from autolab import schemas as s
from autolab.preparation.models import ResourcePin


class ImplementationError(RuntimeError):
    pass


class RequirementMapping(s.Record):
    requirement: s.Text  # JSON field path in the exact ExperimentSpec
    component: s.Text  # filename.py:function_or_class
    rationale: s.Text


class ReviewResponse(s.Record):
    issue_index: int = Field(ge=0)
    disposition: Literal['ACCEPT', 'REJECT', 'NEEDS_CLARIFICATION']
    evidence: s.Text


class ImplementationPlan(s.ExperimentLinked):
    implementation_id: s.Text
    revision: int = Field(ge=0, le=2)
    spec_fingerprint: s.Text
    manifest_fingerprint: s.Text
    readiness_id: s.Text
    objective: s.Text
    input_resources: list[ResourcePin] = Field(min_length=1, max_length=12)
    expected_files: list[s.Text] = Field(min_length=2, max_length=6)
    components: list[s.Text] = Field(min_length=1, max_length=30)
    conditions: s.JSON
    baseline: s.JSON
    metrics: dict[str, s.Text]
    reproducibility: list[s.Text] = Field(min_length=1, max_length=16)
    seeds: list[int]
    output_schema: s.JSON
    dependencies: list[s.Text] = Field(default_factory=list, max_length=10)
    tests: list[s.Text] = Field(min_length=1, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(min_length=1, max_length=16)
    requirement_mapping: list[RequirementMapping] = Field(min_length=1, max_length=60)
    blockers: list[str] = Field(default_factory=list, max_length=16)
    issue_responses: list[ReviewResponse] = Field(default_factory=list, max_length=30)


class SourceBundle(s.Record):
    files: dict[str, s.Text]


class Probe(s.Record):
    """Framework-owned, configured independently of generated tests/source."""
    component: s.Text
    args: list = Field(default_factory=list)
    expected: object = None
    raises: str | None = None
    requirement: s.Text


class TestContract(s.Record):
    spec_fingerprint: s.Text
    probes: list[Probe] = Field(min_length=1, max_length=80)
    required_components: list[s.Text] = Field(min_length=1)
    metric_requirements: dict[str, s.Text]
    setup_context: s.JSON = Field(default_factory=dict)
    fixture_resources: dict[str, object] = Field(default_factory=dict)
    expected_setup: s.JSON = Field(default_factory=dict)
    expected_seeds: list[int]
    provenance: s.Text


class CheckReport(s.Record):
    static_pass: bool
    findings: list[str] = Field(default_factory=list)
    tests_pass: bool = False
    test_count: int = 0
    generated_count: int = 0
    exit_status: int | None = None
    timed_out: bool = False
    output: str = ''


class ImplementationResult(s.Record):
    implementation_id: s.Text
    status: Literal['AUDIT_PENDING', 'READY', 'REVISE', 'BLOCK']
    revision_rounds: int = Field(ge=0, le=2)
    review_ids: list[str] = Field(default_factory=list)
    code_hash: str
    scientific_experiment_executed: Literal[False] = False
