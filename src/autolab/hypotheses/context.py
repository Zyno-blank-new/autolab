"""Compact evidence and proposal context, without abstracts or hidden reasoning."""
import re
from autolab import schemas as s
from autolab.orchestration.state_machine import latest_versions, latest_review
from .models import HypothesisContext, HypothesisLimits, HypothesisOutputError


def is_contradictory(evidence):
    return any(tag.upper() == "CONTRADICTING" for tag in evidence.tags)


def hypothesis_summary(h, review=None, *, chars=1200):
    return {"id": h.hypothesis_id, "version": h.version, "statement": h.statement[:chars],
        "falsifiable_prediction": h.falsifiable_prediction[:chars], "status": h.status.value,
        "origin": "agent-generated hypothesis; not evidence" if h.rationale.startswith("AGENT-GENERATED HYPOTHESIS") else "unspecified proposal origin; not evidence", "novelty_score": h.novelty_score,
        "testability_score": h.testability_score, "scientific_value_score": h.scientific_value_score,
        "supporting_evidence_ids": h.supporting_evidence_ids,
        "contradicting_evidence_ids": h.contradicting_evidence_ids,
        "critic": {"id": review.review_id, "target_version": review.target_version,
                   "verdict": review.verdict.value, "concerns": review.issues[:3]} if review else None}


def build_context(snapshot, limits=None):
    limits = limits or HypothesisLimits()
    # Contradictions cannot be silently dropped by the evidence bound.
    contradictions = [e for e in snapshot.evidence if is_contradictory(e)]
    if len(contradictions) > limits.max_evidence:
        raise HypothesisOutputError("Contradictory evidence exceeds context bound; increase the explicit limit")
    selected = [*contradictions, *sorted((e for e in snapshot.evidence if not is_contradictory(e)),
                                      key=lambda e: (-e.confidence, e.evidence_id))][:limits.max_evidence]
    sources = {source.source_id: source for source in snapshot.sources}
    evidence = [{"id": e.evidence_id, "source_id": e.source_id,
        "source_title": sources[e.source_id].title[:240] if e.source_id in sources else None,
        "claim": e.claim[:limits.summary_chars], "supporting_text": e.supporting_text[:limits.summary_chars],
        "location": e.location, "confidence": e.confidence, "tags": e.tags[:10]} for e in selected]
    latest = latest_versions(snapshot.hypotheses, "hypothesis_id")
    rejected = [h for h in latest if h.status == s.HypothesisStatus.REJECTED or any(
        r.target_id == h.hypothesis_id and r.verdict == s.ReviewVerdict.REJECT
        and r.target_version == h.version for r in snapshot.reviews)]
    from autolab.orchestration.adaptive import hypothesis_disposition
    rejected = [h for h in latest if h in rejected or hypothesis_disposition(snapshot, h) == 'HYPOTHESIS_REJECTED']
    context = HypothesisContext(charter=snapshot.charter, evidence=evidence,
        prior_decisions=[{"id": d.decision_id, "action": d.action.value, "reason": d.reason[:400]}
                         for d in snapshot.decisions[-5:]],
        rejected_hypotheses=[{"id": h.hypothesis_id, "status": "REJECTED", "statement": h.statement[:600]}
                             for h in rejected[-10:]],
        existing_hypotheses=[hypothesis_summary(h, latest_review(snapshot, s.Hypothesis, h.hypothesis_id, h.version), chars=600)
                             for h in latest[-10:]], omitted_evidence_count=len(snapshot.evidence)-len(selected))
    from autolab.orchestration.adaptive import result_packet
    context = context.model_copy(update={'reviewed_result': result_packet(snapshot)})
    if len(context.model_dump_json()) > limits.max_context_chars:
        raise HypothesisOutputError("Hypothesis context exceeds configured size; reduce summaries or increase explicit bound")
    return context


def critic_packet(context, hypotheses, *, all_candidates=None, responses=None):
    """Each target gets referenced evidence and every supplied contradiction."""
    all_candidates = all_candidates if all_candidates is not None else hypotheses
    entries = []
    for hypothesis in hypotheses:
        refs = set(hypothesis.supporting_evidence_ids + hypothesis.contradicting_evidence_ids)
        refs.update(re.findall(r"\bEVID_[A-Za-z0-9_]+\b", hypothesis.rationale + " " + hypothesis.statement + " " + hypothesis.falsifiable_prediction))
        entries.append({"hypothesis": hypothesis.model_dump(mode="json"),
            "evidence": [e for e in context.evidence if e["id"] in refs or "CONTRADICTING" in [t.upper() for t in e["tags"]]],
            "other_candidates": [hypothesis_summary(h) for h in all_candidates if h.hypothesis_id != hypothesis.hypothesis_id]})
    return {"research_charter": context.charter.model_dump(mode="json"), "targets": entries,
            "reviewed_result": context.reviewed_result,
            "scientific_limits": context.scientific_limits,
            "revision_responses": [r.model_dump(mode="json") for r in responses or []]}
