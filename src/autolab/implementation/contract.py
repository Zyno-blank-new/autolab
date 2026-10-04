"""Stable interface declarations only. Phase 10 will own scientific execution."""
from abc import ABC, abstractmethod
from pydantic import Field
from autolab import schemas as s


class BaseExperiment(ABC):
    @abstractmethod
    def setup(self, context):
        """Bind validated inputs and configuration without running science."""

    @abstractmethod
    def run(self, context):
        """Phase 10 entry point; Phase 9 must never invoke this method."""

    @abstractmethod
    def collect_results(self, context):
        """Return structured raw observations, with no invented metrics."""


class RawObservation(s.Record):
    condition: s.Text
    sample_id: s.Text
    outputs: s.JSON
    status: str
    failure_category: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    timings: dict[str, s.Nonnegative] = Field(default_factory=dict)
    artifact_references: list[str] = Field(default_factory=list)


class ExperimentRawOutput(s.Record):
    experiment_id: s.Text
    experiment_version: s.Version
    observations: list[RawObservation]
    metadata: s.JSON = Field(default_factory=dict)
