"""Workflow envelopes reuse canonical Hypothesis and ReviewRecord directly."""
from typing import Literal
from pydantic import Field, model_validator
from autolab import schemas as s


class HypothesisOutputError(RuntimeError):
    pass


class HypothesisLimits(s.Record):
    candidate_count: int = Field(default=3, ge=1, le=5)
    max_revision_rounds: Literal[0, 1] = 1
    max_evidence: int = Field(default=24, ge=1, le=80)
    summary_chars: int = Field(default=1200, ge=200, le=2400)
    max_context_chars: int = Field(default=45000, ge=4000, le=100000)


class HypothesisContext(s.Record):
    charter: s.ResearchCharter
    evidence: list[s.JSON]
    prior_decisions: list[s.JSON]
    rejected_hypotheses: list[s.JSON]
    existing_hypotheses: list[s.JSON]
    omitted_evidence_count: int = 0
    reviewed_result: s.JSON = Field(default_factory=dict)
    scientific_limits: list[str] = Field(default_factory=lambda: [
        "Hypotheses are agent-generated proposals, never evidence or established facts.",
        "Novelty scores are relative to retrieved evidence and the current research state only.",
        "Abstract evidence does not establish full methodological validity."])


class HypothesisBatch(s.Record):
    hypotheses: list[s.Hypothesis] = Field(max_length=5)
    insufficient_basis: str | None = None

    @model_validator(mode="after")
    def basis(self):
        if not self.hypotheses and not (self.insufficient_basis or "").strip():
            raise ValueError("An empty batch must explain the insufficient scientific basis.")
        if self.hypotheses and self.insufficient_basis:
            raise ValueError("Return candidates or an insufficient-basis explanation, not both.")
        return self


class ReviewBatch(s.Record):
    reviews: list[s.ReviewRecord] = Field(min_length=1, max_length=5)


class CritiqueResponse(s.Record):
    review_id: s.Text
    issue_index: int = Field(ge=0)
    disposition: Literal["ACCEPT", "REBUT", "CLARIFY"]
    reason: s.Text
    evidence_ids: list[s.Text] = Field(default_factory=list)


class RevisionBatch(s.Record):
    hypotheses: list[s.Hypothesis] = Field(min_length=1, max_length=5)
    responses: list[CritiqueResponse] = Field(max_length=40)


class HypothesisGenerationResult(s.Record):
    project_id: str
    hypothesis_ids: list[str]
    review_ids: list[str]
    passed_hypothesis_ids: list[str]
    rejected_hypothesis_ids: list[str]
    revised_hypothesis_ids: list[str]
    unresolved_hypothesis_ids: list[str]
    revision_rounds: int
    warnings: list[str]
    summary: str
