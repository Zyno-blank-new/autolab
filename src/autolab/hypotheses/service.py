"""Persist proposals → critique → one revision/rebuttal → return to PI."""
from pydantic import ValidationError
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.budget import calculate_budget
from autolab.planner.service import PlannerInvocationError, runtime_metadata
from .agent import OmnigentHypothesisAgent, OmnigentScientificCritic
from .context import build_context
from .models import HypothesisLimits, HypothesisGenerationResult, HypothesisOutputError
from .validation import validate_hypotheses, validate_reviews, validate_responses


class HypothesisPipeline:
    def __init__(self, ledger: ResearchLedger, agent=None, critic=None, limits=None):
        self.ledger = ledger
        self.agent = agent if agent is not None else OmnigentHypothesisAgent()
        self.critic = critic if critic is not None else OmnigentScientificCritic()
        self.limits = limits or HypothesisLimits()

    def _allowed(self, project_id):
        snapshot = load_snapshot(self.ledger, project_id)
        # Reuse the routine scientific-work gate, including for an isolated
        # no-evidence proposal. Planner GENERATE routing still requires evidence.
        check = DecisionValidator().validate(s.NextDecision(decision_id="DEC_HYPOTHESIS_GATE",
            project_id=project_id, action=s.PlannerAction.GATHER_EVIDENCE, target_agent="evidence",
            reason="Check routine hypothesis reasoning gate", remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd), snapshot)
        if not check.valid:
            raise HypothesisOutputError("Hypothesis workflow blocked: " + "; ".join(check.reasons))
        return snapshot

    def _event(self, project, kind, summary, payload=None, hypothesis=None):
        payload = dict(payload or {})
        client = self.critic if kind == "HYPOTHESIS_REVIEWED" else self.agent
        if kind in ("HYPOTHESIS_CREATED", "HYPOTHESIS_REVISED", "HYPOTHESIS_REVIEWED"):
            metadata = runtime_metadata(client)
            if metadata:
                payload["model_metadata"] = metadata
        return s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project,
            event_type=kind, actor="critic" if kind == "HYPOTHESIS_REVIEWED" else "hypothesis",
            target_type="hypotheses" if hypothesis else None, target_id=hypothesis,
            summary=summary, payload=payload)

    def _commit(self, project_id, records, baseline):
        def check():
            fresh = self._allowed(project_id)
            # Preserve completed history but reject concurrent scientific writes
            # or superseded PI decisions. Own audit events need no full comparison.
            for field in ("charter", "authorized_scope", "sources", "evidence", "hypotheses", "reviews", "decisions",
                          "experiments", "runs", "metrics", "analyses", "costs"):
                if getattr(fresh, field) != getattr(baseline, field):
                    raise HypothesisOutputError("Research state changed; rebuild hypothesis context")
        self.ledger.add_many(records, check=check)
        return self._allowed(project_id)

    def _assign(self, hypotheses=None, project_id=None):
        if hypotheses is None:
            return [{"hypothesis_id": self.ledger.next_id("HYP"), "project_id": project_id, "version": 1}
                    for _ in range(self.limits.candidate_count)]
        return [{"hypothesis_id": h.hypothesis_id, "project_id": h.project_id, "version": h.version+1} for h in hypotheses]

    def _review_assignments(self, hypotheses):
        return [{"review_id": self.ledger.next_id("HREV"), "target_id": h.hypothesis_id,
                 "target_version": h.version, "project_id": h.project_id} for h in hypotheses]

    async def generate(self, project_id):
        snapshot = self._allowed(project_id)
        context = build_context(snapshot, self.limits)
        self.ledger.add_event(self._event(project_id, "HYPOTHESIS_GENERATION_STARTED", "Starting bounded evidence-aware hypothesis generation"))
        try:
            return await self._generate(snapshot, context)
        except (ValidationError, HypothesisOutputError, PlannerInvocationError) as error:
            self.ledger.add_event(self._event(project_id, "HYPOTHESIS_GENERATION_FAILED",
                "Hypothesis workflow failed; completed records preserved, invalid output rejected"))
            if isinstance(error, ValidationError):
                raise HypothesisOutputError("Hypothesis/review output violates the canonical schema") from None
            raise

    async def refine(self, project_id, *, critique_only=False):
        from autolab.orchestration.state_machine import selected_hypothesis
        snapshot = self._allowed(project_id)
        context = build_context(snapshot, self.limits)
        original = selected_hypothesis(snapshot)
        if original is None:
            raise HypothesisOutputError('Refinement requires an exact selected hypothesis')
        baseline = snapshot
        refined = original
        if not critique_only:
            assignments = self._assign([original])
            batch = validate_hypotheses(await self.agent.refine(context, original, assignments), context,
                self.ledger, assignments, existing=snapshot.hypotheses, revised=True)
            if batch.responses or batch.hypotheses[0].falsifiable_prediction == original.falsifiable_prediction:
                raise HypothesisOutputError('Refinement must change the falsifiable prediction; no fabricated critique responses')
            refined = batch.hypotheses[0].model_copy(update={'created_at': s.utc_now()})
            baseline = self._commit(project_id, [refined, self._event(project_id, 'HYPOTHESIS_REFINED',
                'Planner-requested new hypothesis version; original evidence and result retained',
                {'parent_version': original.version, 'version': refined.version,
                 'trigger_decision': snapshot.decisions[-1].decision_id,
                 'reviewed_parent_result': context.reviewed_result}, refined.hypothesis_id),
                s.EventRecord(event_id=self.ledger.next_id('EVENT'), project_id=project_id,
                    event_type='HYPOTHESIS_SELECTED', actor='orchestrator', target_type='hypotheses',
                    target_id=refined.hypothesis_id, summary='Refined version selected for independent critique',
                    payload={'hypothesis_id': refined.hypothesis_id, 'version': refined.version})], snapshot)
        reviews = await self._review(context, [refined], [refined])
        self._persist_reviews(project_id, reviews, baseline)
        return self._result(project_id, [refined], reviews, [refined.hypothesis_id], 0,
                            ['Refinement is a new proposal, not acceptance or proof; control returns to PI'])

    async def _generate(self, snapshot, context):
        project_id = context.charter.project_id
        assignments = self._assign(project_id=project_id)
        output = validate_hypotheses(await self.agent.generate(context, assignments), context, self.ledger,
                                     assignments, existing=snapshot.hypotheses)
        candidates = [h.model_copy(update={"created_at": s.utc_now()}) for h in output.hypotheses]
        if not candidates:
            result = self._result(project_id, [], [], [], 0, ["Insufficient scientific basis: " + output.insufficient_basis])
            self._commit(project_id, [self._event(project_id, "HYPOTHESIS_GENERATION_COMPLETED", result.summary,
                {"hypothesis_ids": [], "insufficient_basis": output.insufficient_basis})], snapshot)
            return result
        events = [self._event(project_id, "HYPOTHESIS_CREATED", "Agent-generated falsifiable proposal registered",
            {"version": h.version, "origin": "agent-generated", "evidence_ids": h.supporting_evidence_ids+h.contradicting_evidence_ids}, h.hypothesis_id) for h in candidates]
        baseline = self._commit(project_id, [*candidates, *events], snapshot)
        reviews = await self._review(context, candidates, candidates)
        baseline = self._persist_reviews(project_id, reviews, baseline)
        all_reviews = list(reviews)
        revised_ids, rounds = [], 0
        needs_revision = [h for h in candidates if next(r for r in reviews if r.target_id == h.hypothesis_id).verdict == s.ReviewVerdict.REVISE]
        if needs_revision and self.limits.max_revision_rounds:
            self._allowed(project_id)
            revision_reviews = [r for r in reviews if r.target_id in {h.hypothesis_id for h in needs_revision}]
            assignments = self._assign(needs_revision)
            revision = validate_hypotheses(await self.agent.revise(context, needs_revision, revision_reviews, assignments),
                context, self.ledger, assignments, existing=baseline.hypotheses, revised=True)
            validate_responses(revision, revision_reviews, context, self.ledger)
            revised = [h.model_copy(update={"created_at": s.utc_now()}) for h in revision.hypotheses]
            events = [self._event(project_id, "HYPOTHESIS_REVISED", "Single revision/rebuttal recorded as a new canonical version",
                {"version": h.version, "responses": [r.model_dump(mode="json") for r in revision.responses
                    if r.review_id in {review.review_id for review in revision_reviews if review.target_id == h.hypothesis_id}]}, h.hypothesis_id) for h in revised]
            baseline = self._commit(project_id, [*revised, *events], baseline)
            replacements = {h.hypothesis_id: h for h in revised}
            candidates = [replacements.get(h.hypothesis_id, h) for h in candidates]
            final_reviews = await self._review(context, revised, candidates, responses=revision.responses)
            baseline = self._persist_reviews(project_id, final_reviews, baseline)
            all_reviews.extend(final_reviews)
            revised_ids = list(replacements)
            rounds = 1
        # A rejection is a status-only canonical version. Its scientific review
        # remains pinned to the evaluated version; we never fabricate a re-review.
        rejected_versions, rejection_events = [], []
        for h in candidates:
            verdict = next(r.verdict for r in reversed(all_reviews) if r.target_id == h.hypothesis_id)
            if verdict == s.ReviewVerdict.REJECT:
                rejected_versions.append(h.model_copy(update={"status": s.HypothesisStatus.REJECTED, "version": h.version+1, "created_at": s.utc_now()}))
                rejection_events.append(self._event(project_id, "HYPOTHESIS_REJECTED", "Critic-rejected proposal retained in versioned memory",
                    {"reviewed_version": h.version, "version": h.version+1}, h.hypothesis_id))
        result = self._result(project_id, candidates, all_reviews, revised_ids, rounds,
            ["Hypotheses are agent-generated; PASS permits investigation, not factual acceptance.",
             "Novelty/scores are local advisory assessments. Actual model costs are unavailable and not inferred."])
        completed = self._event(project_id, "HYPOTHESIS_GENERATION_COMPLETED", result.summary,
            {"hypothesis_ids": result.hypothesis_ids, "review_ids": result.review_ids, "revision_rounds": rounds,
             "passed_hypothesis_ids": result.passed_hypothesis_ids, "unresolved_hypothesis_ids": result.unresolved_hypothesis_ids})
        self._commit(project_id, [*rejected_versions, *rejection_events, completed], baseline)
        return result

    async def _review(self, context, hypotheses, all_candidates, responses=None):
        self._allowed(context.charter.project_id)
        assignments = self._review_assignments(hypotheses)
        batch = await self.critic.review(context, hypotheses, assignments, all_candidates=all_candidates, responses=responses)
        batch = validate_reviews(batch, hypotheses, context, assignments)
        return [r.model_copy(update={"created_at": s.utc_now()}) for r in batch.reviews]

    def _persist_reviews(self, project_id, reviews, baseline):
        events = [self._event(project_id, "HYPOTHESIS_REVIEWED", "Independent Scientific Critic verdict recorded",
            {"review_id": r.review_id, "version": r.target_version, "verdict": r.verdict.value}, r.target_id) for r in reviews]
        return self._commit(project_id, [*reviews, *events], baseline)

    @staticmethod
    def _result(project_id, hypotheses, reviews, revised, rounds, warnings):
        ids = [h.hypothesis_id for h in hypotheses]
        latest = {r.target_id: r.verdict for r in reviews}
        return HypothesisGenerationResult(project_id=project_id, hypothesis_ids=ids,
            review_ids=[r.review_id for r in reviews], passed_hypothesis_ids=[i for i in ids if latest[i] == s.ReviewVerdict.PASS],
            rejected_hypothesis_ids=[i for i in ids if latest[i] == s.ReviewVerdict.REJECT], revised_hypothesis_ids=revised,
            unresolved_hypothesis_ids=[i for i in ids if latest[i] in (s.ReviewVerdict.REVISE, s.ReviewVerdict.BLOCK)],
            revision_rounds=rounds, warnings=warnings,
            summary=f"Generated {len(ids)} agent-generated hypotheses; persisted {len(reviews)} reviews; revision rounds {rounds}. Control returns to Planner.")
