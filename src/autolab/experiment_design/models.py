"""Workflow envelopes contain the canonical candidates and reviews."""
from typing import Literal
from pydantic import Field
from autolab import schemas as s
from autolab.hypotheses.models import CritiqueResponse


class ExperimentDesignError(RuntimeError):
    pass


class DesignLimits(s.Record):
    candidate_count: int = Field(default=2, ge=2, le=3)
    max_revision_rounds: Literal[0, 1] = 1
    max_evidence: int = Field(default=16, ge=1, le=40)
    summary_chars: int = Field(default=900, ge=200, le=1800)
    max_context_chars: int = Field(default=35000, ge=4000, le=80000)


class ExperimentDesignContext(s.Record):
    charter: s.ResearchCharter
    hypothesis: s.Hypothesis
    hypothesis_review: s.ReviewRecord
    evidence: list[s.JSON]
    previous_experiments: list[s.JSON]
    previous_candidates: list[s.JSON]
    constraints: s.JSON
    reviewed_result: s.JSON = Field(default_factory=dict)
    scientific_limits: list[str] = Field(default_factory=lambda: [
        "Hypothesis is a proposal; PASS is permission to investigate, not proof.",
        "Abstract-only evidence cannot establish complete methodological validity.",
        "Estimates are rough planning constraints; unknown cost/runtime must be null.",
        "No resources have been prepared and no results are available for these proposals."])


class CandidateBatch(s.Record):
    candidates: list[s.ExperimentCandidate] = Field(min_length=2, max_length=3)


class CandidateRevision(s.Record):
    candidates: list[s.ExperimentCandidate] = Field(min_length=1, max_length=3)
    responses: list[CritiqueResponse] = Field(max_length=24)


class ExperimentDesignResult(s.Record):
    project_id: str
    hypothesis_id: str
    hypothesis_version: int
    candidate_ids: list[str]
    review_ids: list[str]
    final_candidate_ids: list[str]
    rejected_candidate_ids: list[str]
    unresolved_candidate_ids: list[str]
    revision_rounds: int
    selected_candidate_id: str | None = None
    experiment_id: str | None = None
    warnings: list[str]
    summary: str
