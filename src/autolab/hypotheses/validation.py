"""Deterministic identity, project, provenance-label, and duplicate checks."""
import re
import unicodedata
from autolab import schemas as s
from .models import HypothesisBatch, ReviewBatch, RevisionBatch, HypothesisOutputError

LABEL = "AGENT-GENERATED HYPOTHESIS"
SUPPORTED = "SUPPORTED BY EVIDENCE:"
INFERENCE = "SCIENTIFIC INFERENCE / PROPOSED EXPLANATION:"


def normalized_statement(text):
    return " ".join(re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFKC", text).casefold()).split())


def validate_evidence_ids(ids, context, ledger):
    visible = {e["id"] for e in context.evidence}
    for identifier in ids:
        record = ledger.get(s.EvidenceRecord, identifier)
        if record is None or record.project_id != context.charter.project_id or identifier not in visible:
            raise HypothesisOutputError("Evidence citation is nonexistent, foreign-project, or outside supplied context")


def validate_hypotheses(batch, context, ledger, assignments, *, existing=None, revised=False):
    # Revalidation also catches mutated containers and model_copy bypasses.
    schema = RevisionBatch if revised else HypothesisBatch
    batch = schema.model_validate(batch.model_dump())
    if not revised and not batch.hypotheses:
        return batch
    expected = {a["hypothesis_id"]: a["version"] for a in assignments}
    actual = [h.hypothesis_id for h in batch.hypotheses]
    if len(actual) != len(expected) or set(actual) != set(expected):
        raise HypothesisOutputError("Hypothesis batch must contain every assigned candidate exactly once")
    seen = {}
    for old in existing or []:
        seen.setdefault(normalized_statement(old.statement), old.hypothesis_id)
    for hypothesis in batch.hypotheses:
        if len(hypothesis.statement) > 1800 or len(hypothesis.falsifiable_prediction) > 1800 or len(hypothesis.rationale) > 5000:
            raise HypothesisOutputError("Hypothesis text exceeds compact proposal bounds")
        if hypothesis.project_id != context.charter.project_id or hypothesis.version != expected[hypothesis.hypothesis_id]:
            raise HypothesisOutputError("Hypothesis project/version differs from assigned identity")
        status = s.HypothesisStatus.REFINED if revised else s.HypothesisStatus.PROPOSED
        if hypothesis.status != status:
            raise HypothesisOutputError("Hypothesis Agent cannot accept, reject, or select a proposal")
        if not hypothesis.rationale.startswith(LABEL) or SUPPORTED not in hypothesis.rationale or INFERENCE not in hypothesis.rationale:
            raise HypothesisOutputError("Rationale must label agent origin and separate evidence from inference")
        if any(score is None for score in (hypothesis.novelty_score, hypothesis.testability_score, hypothesis.scientific_value_score)):
            raise HypothesisOutputError("All advisory hypothesis scores are required")
        ids = hypothesis.supporting_evidence_ids + hypothesis.contradicting_evidence_ids
        # IDs in free text must not bypass explicit lists or fabricate citations.
        mentioned = set(re.findall(r"\bEVID_[A-Za-z0-9_]+\b", hypothesis.rationale + " " + hypothesis.statement + " " + hypothesis.falsifiable_prediction))
        # Background/context citations need not be mislabeled as directional
        # support. All prose citations still require real visible project IDs.
        validate_evidence_ids([*ids, *mentioned], context, ledger)
        if not ids and "LOW-CONFIDENCE" not in hypothesis.rationale.upper():
            raise HypothesisOutputError("Uncited hypotheses must explicitly state LOW-CONFIDENCE inference")
        key = normalized_statement(hypothesis.statement)
        if not key or (key in seen and seen[key] != hypothesis.hypothesis_id):
            raise HypothesisOutputError("Identical normalized hypothesis already exists; do not create another ID")
        seen[key] = hypothesis.hypothesis_id
    return batch


def validate_reviews(batch, hypotheses, context, assignments):
    batch = ReviewBatch.model_validate(batch.model_dump())
    targets = {h.hypothesis_id: h.version for h in hypotheses}
    expected = {a["target_id"]: a["review_id"] for a in assignments}
    if len(batch.reviews) != len(targets) or {r.target_id for r in batch.reviews} != set(targets):
        raise HypothesisOutputError("Critic must review each supplied hypothesis exactly once")
    visible = {e["id"] for e in context.evidence}
    for review in batch.reviews:
        if len(review.model_dump_json()) > 8000:
            raise HypothesisOutputError("Critic review exceeds compact text bounds")
        if (review.project_id != context.charter.project_id or review.review_id != expected[review.target_id]
            or review.target_version != targets[review.target_id] or review.target_type != "hypotheses"
            or review.review_type != "hypothesis" or review.reviewer_role != "critic"):
            raise HypothesisOutputError("Critic review must reference the assigned project and exact hypothesis/version")
        if len(review.issues) > 8 or len(review.questions) > 5 or len(review.recommendations) > 5:
            raise HypothesisOutputError("Critic feedback exceeds compact review bounds")
        if review.verdict != s.ReviewVerdict.PASS and not review.issues:
            raise HypothesisOutputError("Non-PASS review requires specific scientific issues")
        for issue in review.issues:
            for field in ("problem", "why_it_matters", "resolution"):
                if not isinstance(issue.get(field), str) or not issue[field].strip():
                    raise HypothesisOutputError("Critic issue must explain problem, importance, and resolution")
            ids = issue.get("evidence_ids", [])
            if not isinstance(ids, list) or any(i not in visible for i in ids):
                raise HypothesisOutputError("Critic issue cites unavailable evidence")
        prose = review.model_dump_json()
        if any(i not in visible for i in re.findall(r"\bEVID_[A-Za-z0-9_]+\b", prose)):
            raise HypothesisOutputError("Critic references fabricated evidence")
    return batch


def validate_responses(batch, reviews, context, ledger):
    expected = {(r.review_id, i) for r in reviews for i in range(len(r.issues))}
    actual = [(r.review_id, r.issue_index) for r in batch.responses]
    if len(actual) != len(expected) or set(actual) != expected:
        raise HypothesisOutputError("Revision must ACCEPT, REBUT, or CLARIFY each material critique exactly once")
    for response in batch.responses:
        validate_evidence_ids(response.evidence_ids, context, ledger)
        if any(i not in response.evidence_ids for i in re.findall(r"\bEVID_[A-Za-z0-9_]+\b", response.reason)):
            raise HypothesisOutputError("Rebuttal cites evidence outside its reference list")
