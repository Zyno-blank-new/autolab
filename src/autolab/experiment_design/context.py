"""Role-specific evidence and design history, bounded before paid calls."""
import re
from autolab import schemas as s
from autolab.orchestration.budget import calculate_budget, calculate_time
from autolab.orchestration.state_machine import selected_hypothesis, latest_review, latest_versions
from .models import ExperimentDesignContext, DesignLimits, ExperimentDesignError


def candidate_summary(candidate, review=None, chars=500):
    return {"id": candidate.candidate_id, "version": candidate.version, "hypothesis_id": candidate.hypothesis_id,
        "hypothesis_version": candidate.hypothesis_version, "title": candidate.title[:chars], "objective": candidate.objective[:chars],
        "approach": candidate.approach[:chars], "primary_metric": str(candidate.design.get("primary_metric", ""))[:chars],
        "metric_rationale": str(candidate.design.get("metric_rationale", ""))[:chars],
        "expected_information_gain": candidate.expected_information_gain, "feasibility_score": candidate.feasibility_score,
        "major_risks": [x[:chars] for x in candidate.major_risks[:3]], "status": candidate.status.value,
        "estimated_cost_usd": candidate.estimated_cost_usd, "estimated_runtime_minutes": candidate.estimated_runtime_minutes,
        "estimates_scope": "rough planning only; null means unknown; Phase 7 must resolve",
        "success_criteria": str(candidate.design.get("success_criteria", {}))[:chars],
        "falsification_criteria": str(candidate.design.get("falsification_criteria", {}))[:chars],
        "critic": None if review is None else {"id": review.review_id, "verdict": review.verdict.value,
            "reviewed_version": review.target_version, "concerns": [{"problem": str(x.get("problem", ""))[:chars],
                "resolution": str(x.get("resolution", ""))[:chars]} for x in review.issues[:2]]}}


def candidate_history_summary(snapshot, candidate, chars=500):
    review = latest_review(snapshot, s.ExperimentCandidate, candidate.candidate_id, candidate.version, "experiment")
    if review is None and candidate.status == s.ExperimentStatus.CANCELLED:
        review = next((r for r in reversed(snapshot.reviews) if r.target_id == candidate.candidate_id
            and r.target_type in ("ExperimentCandidate", "experiment_candidates") and r.review_type == "experiment"), None)
    row = candidate_summary(candidate, review, chars=chars)
    selection = next((e for e in reversed(snapshot.events) if e.event_type == "EXPERIMENT_SELECTED"
        and e.payload.get("candidate_id") == candidate.candidate_id), None)
    row["selected_experiment_id"] = selection.payload.get("experiment_id") if selection else None
    return row


def build_context(snapshot, limits=None):
    limits = limits or DesignLimits()
    hypothesis = selected_hypothesis(snapshot)
    if hypothesis is None or hypothesis.status == s.HypothesisStatus.REJECTED:
        raise ExperimentDesignError("Experiment design requires one canonically selected non-rejected hypothesis")
    review = latest_review(snapshot, s.Hypothesis, hypothesis.hypothesis_id, hypothesis.version, "hypothesis")
    if review is None or review.verdict != s.ReviewVerdict.PASS or review.reviewer_role != "critic":
        raise ExperimentDesignError("Selected exact hypothesis version requires a PASS Scientific Critic assessment")
    ids = set(hypothesis.supporting_evidence_ids + hypothesis.contradicting_evidence_ids)
    ids.update(re.findall(r"\bEVID_[A-Za-z0-9_]+\b", hypothesis.rationale))
    evidence = [e for e in snapshot.evidence if e.evidence_id in ids or "CONTRADICTING" in e.tags]
    if not ids <= {e.evidence_id for e in evidence}:
        raise ExperimentDesignError("Selected hypothesis has unavailable evidence")
    if len(evidence) > limits.max_evidence:
        raise ExperimentDesignError("Relevant evidence exceeds design context bound; contradictions cannot be dropped")
    cut = lambda value: value[:limits.summary_chars]
    time = calculate_time(snapshot)
    context = ExperimentDesignContext(charter=snapshot.charter, hypothesis=hypothesis, hypothesis_review=review,
        evidence=[{"id": e.evidence_id, "source_id": e.source_id, "claim": cut(e.claim),
            "supporting_text": cut(e.supporting_text), "location": e.location, "confidence": e.confidence, "tags": e.tags[:10]} for e in evidence],
        previous_experiments=[{"id": e.experiment_id, "version": e.version, "hypothesis_id": e.hypothesis_id,
            "objective": cut(e.objective), "primary_metric": e.primary_metric, "status": e.status.value,
            "outcomes": [{"run_id": a.run_id, "assessment": a.hypothesis_assessment.value,
                "interpretation": cut(a.interpretation)} for a in snapshot.analyses if a.experiment_id == e.experiment_id and a.experiment_version == e.version][-2:]}
            for e in latest_versions(snapshot.experiments, "experiment_id") if e.hypothesis_id == hypothesis.hypothesis_id][-6:],
        previous_candidates=[candidate_history_summary(snapshot, c, chars=350)
            for c in latest_versions(snapshot.candidates, "candidate_id") if c.hypothesis_id == hypothesis.hypothesis_id][-6:],
        constraints={"remaining_budget_usd": calculate_budget(snapshot).remaining_budget_usd,
            "remaining_time_minutes": time.remaining_minutes,
            "known_capability_categories": sorted({r.resource_type for r in snapshot.resources}),
            "capability_availability": "not independently audited; no new resources may be acquired"})
    from autolab.orchestration.adaptive import result_packet
    context = context.model_copy(update={'reviewed_result': result_packet(snapshot)})
    if not context.reviewed_result:
        refined = next((e for e in reversed(snapshot.events) if e.event_type == 'HYPOTHESIS_REFINED'
            and e.actor == 'hypothesis' and e.target_id == hypothesis.hypothesis_id and e.payload.get('version') == hypothesis.version), None)
        if refined and refined.payload.get('reviewed_parent_result'):
            context = context.model_copy(update={'reviewed_result': {**refined.payload['reviewed_parent_result'],
                'eligibility': 'Historical reviewed parent evidence only; not support for refined hypothesis'}})
    if snapshot.authorized_scope:
        context.constraints['authorized_research_scope'] = snapshot.authorized_scope.model_dump(mode='json')
    if context.reviewed_result:
        context.scientific_limits[-1] = 'Existing reviewed measurements are supplied; new candidates have no results. Target remaining uncertainty, not automatic repetition.'
    if len(context.model_dump_json()) > limits.max_context_chars:
        raise ExperimentDesignError("ExperimentDesignContext exceeds configured compact bound")
    return context
