from typing import Literal
from pydantic import Field
from autolab import schemas as s


class RuntimeErrorRecord(ValueError):
    """An execution/integrity boundary failed; never a scientific verdict."""


class RunConfig(s.Record):
    run_id: s.Text
    project_id: s.Text
    experiment_id: s.Text
    experiment_version: s.Version
    implementation_id: s.Text
    implementation_hash: s.Text
    manifest_id: s.Text
    manifest_hash: s.Text
    dependency_pins: s.JSON
    charter_hash: s.Text
    adapter_id: s.Text
    seed: int
    timeout_seconds: float = Field(default=10, gt=0, le=60, allow_inf_nan=False)
    working_directory: s.Text
    network_policy: Literal['offline'] = 'offline'
    environment_policy: Literal['explicit-nonsecret-allowlist'] = 'explicit-nonsecret-allowlist'
    retries: Literal[0] = 0
    max_output_bytes: int = Field(default=262144, ge=1024, le=1048576)
    max_log_bytes: int = Field(default=8192, ge=1024, le=65536)
    max_observations: int = Field(ge=1, le=10000)
    deterministic: bool = True


class MetricJob(s.Record):
    metric_name: s.Text
    role: Literal['primary','secondary']
    condition: s.Text
    component: s.Text
    args: list[s.JsonValue]
    denominator: int = Field(ge=1)
    support: s.JSON = Field(default_factory=dict)
    unit: str | None = None


class ProcessReceipt(s.Record):
    exit_status: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    output_exceeded: bool = False
    stdout: str = ''
    stderr: str = ''
    messages: list[s.JSON] = Field(default_factory=list)
