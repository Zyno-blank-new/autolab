"""Candidate proposals → one reusable Critic → bounded revision → central PI."""
from pydantic import ValidationError
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.budget import calculate_budget
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.planner.service import PlannerInvocationError
from autolab.hypotheses.agent import OmnigentScientificCritic
from autolab.hypotheses.models import HypothesisOutputError
from .agent import OmnigentExperimentDesigner
from .context import build_context
from .models import DesignLimits, ExperimentDesignResult, ExperimentDesignError
from .validation import validate_candidates, validate_reviews, validate_responses


class ExperimentDesignPipeline:
    def __init__(self, ledger: ResearchLedger, designer=None, critic=None, limits=None):
        self.ledger = ledger
        self.designer = designer if designer is not None else OmnigentExperimentDesigner()
        self.critic = critic if critic is not None else OmnigentScientificCritic()
        self.limits = limits or DesignLimits()

    def _allowed(self, project_id):
        snapshot = load_snapshot(self.ledger, project_id)
        gate = DecisionValidator().validate(s.NextDecision(decision_id="DEC_DESIGN_GATE", project_id=project_id,
            action=s.PlannerAction.GATHER_EVIDENCE, target_agent="evidence", reason="Routine scientific design gate",
            remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd), snapshot)
        if not gate.valid:
            raise ExperimentDesignError("Experiment design blocked: " + "; ".join(gate.reasons))
        return snapshot

    def _event(self, project, kind, summary, payload=None, candidate=None):
        return s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project, event_type=kind,
            actor="critic" if kind == "EXPERIMENT_CANDIDATE_REVIEWED" else "experiment_designer",
            target_type="experiment_candidates" if candidate else None, target_id=candidate,
            summary=summary, payload=payload or {})

    def _commit(self, project, records, baseline):
        def check():
            fresh = self._allowed(project)
            # Own events may change, but selection/lifecycle and every scientific
            # document must remain current while an external model is reasoning.
            for field in type(baseline).model_fields:
                if field == "events":
                    relevant = lambda x: [e for e in x.events if e.event_type in (
                        "HYPOTHESIS_SELECTED", "EXPERIMENT_SELECTED", "PROJECT_PAUSED", "PROJECT_RESUMED", "PROJECT_BLOCKED", "PROJECT_UNBLOCKED")]
                    changed = relevant(fresh) != relevant(baseline)
                else:
                    changed = getattr(fresh, field) != getattr(baseline, field)
                if changed:
                    raise ExperimentDesignError("Research state changed during design; rebuild context")
        self.ledger.add_many(records, check=check)
        return self._allowed(project)

    def _assign(self, context, candidates=None):
        return [{"candidate_id": c.candidate_id, "version": c.version+1,
            "project_id": c.project_id, "hypothesis_id": c.hypothesis_id, "hypothesis_version": c.hypothesis_version} for c in candidates] if candidates is not None else [
            {"candidate_id": self.ledger.next_id("CAND"), "version": 1, "project_id": context.charter.project_id,
             "hypothesis_id": context.hypothesis.hypothesis_id, "hypothesis_version": context.hypothesis.version}
            for _ in range(self.limits.candidate_count)]

    async def generate(self, project_id):
        baseline = self._allowed(project_id)
        context = build_context(baseline, self.limits)
        self.ledger.add_event(self._event(project_id, "EXPERIMENT_DESIGN_STARTED", "Beginning smallest-informative-test design",
            {"hypothesis_id": context.hypothesis.hypothesis_id, "hypothesis_version": context.hypothesis.version}))
        try:
            return await self._generate(baseline, context)
        except (ValidationError, ExperimentDesignError, HypothesisOutputError, PlannerInvocationError) as error:
            self.ledger.add_event(self._event(project_id, "EXPERIMENT_DESIGN_FAILED",
                "Invalid output rejected; completed candidates and reviews preserved"))
            if isinstance(error, (ValidationError, HypothesisOutputError)):
                raise ExperimentDesignError("Candidate/review/rebuttal violates the scientific design contract") from None
            raise

    async def _review(self, context, candidates, all_candidates, baseline, responses=None):
        self._allowed(context.charter.project_id)
        assignments = [{"review_id": self.ledger.next_id("ERREV"), "project_id": c.project_id,
            "target_id": c.candidate_id, "target_version": c.version} for c in candidates]
        output = await self.critic.review_experiments(context, candidates, assignments,
            all_candidates=all_candidates, responses=responses)
        output = validate_reviews(output, candidates, context, assignments)
        reviews = [r.model_copy(update={"created_at": s.utc_now()}) for r in output.reviews]
        events = [self._event(context.charter.project_id, "EXPERIMENT_CANDIDATE_REVIEWED",
            "Scientific Critic assessed the exact proposal version",
            {"review_id": r.review_id, "version": r.target_version, "verdict": r.verdict.value}, r.target_id) for r in reviews]
        return reviews, self._commit(context.charter.project_id, [*reviews, *events], baseline)

    async def _generate(self, baseline, context):
        project = context.charter.project_id
        assignments = self._assign(context)
        output = validate_candidates(await self.designer.generate(context, assignments), context, assignments, baseline.candidates)
        candidates = [c.model_copy(update={"created_at": s.utc_now()}) for c in output.candidates]
        events = [self._event(project, "EXPERIMENT_CANDIDATE_CREATED", "Structured scientific proposal registered before results",
            {"version": c.version, "hypothesis_id": c.hypothesis_id, "hypothesis_version": c.hypothesis_version}, c.candidate_id) for c in candidates]
        baseline = self._commit(project, [*candidates, *events], baseline)
        return await self._finish(baseline, context, candidates)

    async def review_existing(self, project_id):
        """Explicit reconciliation of persisted proposals with no valid review.

        No generation is repeated, no reviewed proposal is re-reviewed, and the
        existing one-revision bound applies. Normal dispatch does not auto-retry.
        """
        from autolab.orchestration.state_machine import latest_versions, latest_review
        baseline = self._allowed(project_id)
        context = build_context(baseline, self.limits)
        candidates = [c for c in latest_versions(baseline.candidates, 'candidate_id')
            if (c.hypothesis_id, c.hypothesis_version) == (context.hypothesis.hypothesis_id, context.hypothesis.version)]
        candidate_ids={c.candidate_id for c in candidates}
        already_reviewed=any(r.review_type=='experiment' and r.target_id in candidate_ids
            and r.target_type in ('experiment_candidates','ExperimentCandidate') for r in baseline.reviews)
        if (len(candidates) != self.limits.candidate_count or any(c.version!=1 for c in candidates)
            or already_reviewed):
            raise ExperimentDesignError('Reconciliation requires the exact unreviewed candidate batch; no successful work may be repeated')
        self.ledger.add_event(self._event(project_id, 'EXPERIMENT_DESIGN_REVIEW_RECONCILIATION',
            'Explicit review-only reconciliation; original failed dispatch retained; no candidate generation repeated'))
        return await self._finish(self._allowed(project_id), context, candidates)

    async def _finish(self, baseline, context, candidates):
        project = context.charter.project_id
        reviews, baseline = await self._review(context, candidates, candidates, baseline)
        all_reviews = list(reviews)
        to_revise = [c for c in candidates if next(r for r in reviews if r.target_id == c.candidate_id).verdict == s.ReviewVerdict.REVISE]
        rounds = 0
        if to_revise and self.limits.max_revision_rounds:
            self._allowed(project)
            issues = [r for r in reviews if r.target_id in {c.candidate_id for c in to_revise}]
            assignments = self._assign(context, to_revise)
            revision = validate_candidates(await self.designer.revise(context, to_revise, issues, assignments),
                context, assignments, baseline.candidates, revised=True)
            validate_responses(revision, issues, context, self.ledger)
            revised = [c.model_copy(update={"created_at": s.utc_now()}) for c in revision.candidates]
            events = [self._event(project, "EXPERIMENT_CANDIDATE_REVISED", "One revision/rebuttal recorded with complete prior history",
                {"version": c.version, "responses": [x.model_dump(mode="json") for x in revision.responses
                    if x.review_id in {r.review_id for r in issues if r.target_id == c.candidate_id}]}, c.candidate_id) for c in revised]
            baseline = self._commit(project, [*revised, *events], baseline)
            replacements = {c.candidate_id: c for c in revised}
            candidates = [replacements.get(c.candidate_id, c) for c in candidates]
            final, baseline = await self._review(context, revised, candidates, baseline, revision.responses)
            all_reviews.extend(final)
            rounds = 1
        verdicts = {r.target_id: r.verdict for r in all_reviews}
        rejected = [c.candidate_id for c in candidates if verdicts[c.candidate_id] == s.ReviewVerdict.REJECT]
        # CANCELLED is the existing enum for a rejected proposal. Review stays
        # pinned to the scientifically evaluated version, never a fabricated one.
        cancelled = [c.model_copy(update={"version": c.version+1, "status": s.ExperimentStatus.CANCELLED,
            "created_at": s.utc_now()}) for c in candidates if c.candidate_id in rejected]
        events = [self._event(project, "EXPERIMENT_CANDIDATE_REJECTED", "Rejected proposal retained in ledger",
            {"reviewed_version": c.version-1, "version": c.version}, c.candidate_id) for c in cancelled]
        result = ExperimentDesignResult(project_id=project, hypothesis_id=context.hypothesis.hypothesis_id,
            hypothesis_version=context.hypothesis.version, candidate_ids=[c.candidate_id for c in candidates],
            review_ids=[r.review_id for r in all_reviews],
            final_candidate_ids=[c.candidate_id for c in candidates if verdicts[c.candidate_id] == s.ReviewVerdict.PASS],
            rejected_candidate_ids=rejected,
            unresolved_candidate_ids=[c.candidate_id for c in candidates if verdicts[c.candidate_id] in (s.ReviewVerdict.REVISE, s.ReviewVerdict.BLOCK)],
            revision_rounds=rounds, warnings=["Costs/runtime are planning assumptions or unknown; Phase 7 must resolve them.",
                "PASS certifies a design proposal, not prepared resources, adequate power, or approval to execute."],
            summary=f"Registered {len(candidates)} designs and {len(all_reviews)} reviews; {rounds} revision rounds. Control returns to Planner.")
        events.append(self._event(project, "EXPERIMENT_DESIGN_COMPLETED", result.summary, result.model_dump(mode="json")))
        self._commit(project, [*cancelled, *events], baseline)
        return result
