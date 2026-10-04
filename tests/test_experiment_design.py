"""Offline Phase 6: no retrieval, API spending, or experiment execution."""
import asyncio
import copy
import json
import sqlite3
from pathlib import Path
import pytest
from pydantic import ValidationError
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.experiment_design.agent import OmnigentExperimentDesigner
from autolab.experiment_design.context import build_context
from autolab.experiment_design.models import CandidateBatch, CandidateRevision, DesignLimits, ExperimentDesignError
from autolab.experiment_design.service import ExperimentDesignPipeline
from autolab.experiment_design.validation import validate_candidates, validate_design, spec_from_candidate
from autolab.hypotheses.agent import OmnigentScientificCritic
from autolab.hypotheses.models import ReviewBatch, CritiqueResponse
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.orchestrator import Orchestrator, IllegalDecisionError
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_experiment, latest_versions, latest_review, derive_control_state


@pytest.fixture
def project(ledger):
    p = ledger.create_project(s.ResearchCharter(project_id=ledger.next_id("PROJECT"), title="Vision robustness fixture",
        research_question="Does blurring reduce sensitivity to texture shifts?", objective="Discriminate robustness mechanisms",
        primary_outcome="Held-out classification accuracy", budget_usd=10, max_runtime_minutes=60))
    source = ledger.add_source(s.SourceRecord(source_id=ledger.next_id("SRC"), project_id=p.project_id,
        title="Explicit synthetic offline fixture", abstract="Shape and texture affect predictions."))
    evidence = [ledger.add_evidence(s.EvidenceRecord(evidence_id=ledger.next_id("EVID"), project_id=p.project_id,
        source_id=source.source_id, claim=f"Offline fixture {tag}", supporting_text=source.abstract, tags=[tag, "SYNTHETIC_TEST_ONLY"]))
        for tag in ("SUPPORTING", "CONTRADICTING")]
    h = ledger.add_hypothesis(s.Hypothesis(hypothesis_id=ledger.next_id("HYP"), project_id=p.project_id,
        statement="Input blurring improves robustness to texture changes", rationale="Proposed conditional effect",
        falsifiable_prediction="Matched texture changes cause a smaller accuracy decrease with blurring",
        supporting_evidence_ids=[evidence[0].evidence_id], contradicting_evidence_ids=[evidence[1].evidence_id]))
    ledger.add_review(s.ReviewRecord(review_id=ledger.next_id("HREV"), project_id=p.project_id, review_type="hypothesis",
        target_type="hypotheses", target_id=h.hypothesis_id, verdict="PASS", reviewer_role="critic"))
    ledger.add_event(s.EventRecord(event_id=ledger.next_id("EVENT"), project_id=p.project_id,
        event_type="HYPOTHESIS_SELECTED", actor="planner", target_type="hypotheses", target_id=h.hypothesis_id,
        summary="Offline exact-version selection", payload={"hypothesis_id": h.hypothesis_id, "version": h.version}))
    return p


def proposals(context, assignments):
    candidates = []
    for i, assignment in enumerate(assignments):
        design = {"experiment_type": "matched robustness comparison" if i == 0 else "mechanism ablation",
            "independent_variables": {"intervention": "blur/no blur", "condition": "texture shift" if i == 0 else "texture/shape shift"},
            "dependent_variables": {"accuracy_change": "held-out shifted minus clean accuracy"},
            "controls": {"matched": "same inputs, classifier, labels and evaluation budget", "baseline": "no blur"},
            "dataset_requirements": {"modality": "images", "split": "held-out, disjoint from calibration", "labels": "human-verified class labels"},
            "required_resources": ["held-out labeled images", "frozen classifier"],
            "required_capabilities": ["image preprocessing", "deterministic classification evaluation"],
            "primary_metric": "paired change in texture-shift accuracy drop",
            "metric_rationale": "Measures the prediction's conditional robustness effect",
            "secondary_metrics": ["clean accuracy change"],
            "success_criteria": {"scientific": "positive paired robustness benefit with bounded clean accuracy loss"},
            "falsification_criteria": {"scientific": "adequate data exclude meaningful benefit or reveal harm"},
            "potential_confounders": ["blur removes label-relevant shape", "shift severity differs"],
            "assumptions": ["labels remain valid after perturbation"],
            "sampling_strategy": "paired held-out inputs, stratified labels; adequacy unresolved before Phase 7",
            "robustness_checks": ["vary shift severity on locked conditions"],
            "expected_result_patterns": {"supported": "less shifted accuracy loss", "contradicted": "harm or no meaningful benefit with adequate data", "inconclusive": "insufficient examples"},
            "inconclusive_criteria": "uncertainty exceeds the scientifically meaningful effect; resolve adequacy before execution",
            "evidence_ids": [e["id"] for e in context.evidence], "planning_limitations": ["unknown sample adequacy and actual costs"]}
        candidates.append(s.ExperimentCandidate(**assignment, title=f"Design {i}", objective=f"Discriminate effect {i}",
            approach="Paired core effect comparison" if i == 0 else f"Factorial mechanism ablation {i}", design=design,
            expected_information_gain=0.9 if i == 0 else 0.5, feasibility_score=0.8, major_risks=["Label validity"],
            estimated_cost_usd=None, estimated_runtime_minutes=None))
    return CandidateBatch(candidates=candidates)


class FakeDesigner:
    def __init__(self, error=None, disposition="REBUT"):
        self.error, self.disposition, self.calls, self.contexts = error, disposition, [], []
    async def generate(self, context, assignments):
        self.calls.append("generate"); self.contexts.append(context)
        if self.error == "malformed":
            raise ExperimentDesignError("Malformed output")
        output = proposals(context, assignments)
        if self.error == "duplicate":
            output.candidates[1] = output.candidates[1].model_copy(update={"objective": output.candidates[0].objective.upper(), "approach": output.candidates[0].approach+"!"})
        if self.error == "foreign":
            output.candidates[0] = output.candidates[0].model_copy(update={"hypothesis_id": "HYP_OTHER"})
        if self.error == "wrong_metric":
            output.candidates[0].design['primary_metric'] = 'image file size'
        if self.error == "leakage":
            output.candidates[0].design['dataset_requirements']['construction'] = 'Encode target class in a visible image watermark'
        return output
    async def revise(self, context, candidates, reviews, assignments):
        self.calls.append("revise")
        versions = {a['candidate_id']: a['version'] for a in assignments}
        revised = [c.model_copy(update={"version": versions[c.candidate_id], "approach": c.approach+"; clarify locked control"}) for c in candidates]
        if self.error == "revision":
            revised[0] = revised[0].model_copy(update={"version": 1})
        responses = [CritiqueResponse(review_id=r.review_id, issue_index=i, disposition=self.disposition,
            reason="Matched control is preregistered; clarify ambiguity without changing metrics") for r in reviews for i in range(len(r.issues))]
        if self.error == "response":
            responses = []
        return CandidateRevision(candidates=revised, responses=responses)


class FakeCritic:
    def __init__(self, verdicts=None, final="PASS", error=None, callback=None, problem="Control ambiguity"):
        self.verdicts, self.final = verdicts or ["PASS"]*3, final
        self.error, self.callback, self.problem, self.calls, self.contexts = error, callback, problem, [], []
    async def review_experiments(self, context, candidates, assignments, *, all_candidates=None, responses=None):
        self.calls.append("initial" if responses is None else "final"); self.contexts.append(context)
        if self.callback:
            self.callback()
        if self.error == "malformed":
            raise ExperimentDesignError("Malformed critic")
        rows = [s.ReviewRecord(**a, review_type="experiment", target_type="experiment_candidates", reviewer_role="critic",
            verdict=self.verdicts[i] if responses is None else self.final,
            issues=[] if (self.verdicts[i] if responses is None else self.final) == "PASS" else [{"problem": self.problem,
                "why_it_matters": "Cannot discriminate the hypothesized effect fairly", "resolution": "Lock fair control and held-out evaluation", "evidence_ids": []}])
            for i, a in enumerate(assignments)]
        if self.error in ("target_id", "target_version", "target_type", "review_type", "project_id", "reviewer_role", "review_id"):
            values = {"target_id": "CAND_FAKE", "target_version": 99, "target_type": "hypotheses", "review_type": "hypothesis",
                "project_id": "PROJECT_FAKE", "reviewer_role": "designer", "review_id": "ERREV_FAKE"}
            rows[0] = rows[0].model_copy(update={self.error: values[self.error]})
        if self.error == "citation":
            rows[0] = rows[0].model_copy(update={"recommendations": ["EVID_FAKE"]})
        if self.error == "issues":
            rows[0] = rows[0].model_copy(update={"verdict": s.ReviewVerdict.REVISE, "issues": []})
        if self.error == "duplicate":
            rows[1] = rows[0]
        return ReviewBatch(reviews=rows)


def run(ledger, project, designer=None, critic=None, limits=None):
    designer, critic = designer or FakeDesigner(), critic or FakeCritic()
    result = asyncio.run(ExperimentDesignPipeline(ledger, designer, critic, limits).generate(project.project_id))
    return result, designer, critic


class FakePlanner:
    def __init__(self, choice=1, action=s.PlannerAction.SELECT_EXPERIMENT):
        self.choice, self.action, self.contexts = choice, action, []
    async def propose(self, context, decision_id, feedback=None):
        self.contexts.append(context)
        target = {s.PlannerAction.SELECT_EXPERIMENT: "planner", s.PlannerAction.DESIGN_EXPERIMENT: "experiment_designer",
            s.PlannerAction.GATHER_EVIDENCE: "evidence", s.PlannerAction.STOP: None}[self.action]
        ids = [context.current_records['hypothesis']['id']] if self.action == s.PlannerAction.DESIGN_EXPERIMENT else (
            [context.summaries['candidates'][self.choice]['id']] if self.action == s.PlannerAction.SELECT_EXPERIMENT else [])
        return s.NextDecision(decision_id=decision_id, project_id=context.charter.project_id, action=self.action,
            target_agent=target, reason="Mechanism discrimination merits the lower-scored matched ablation",
            required_context_ids=ids, remaining_budget_usd=context.budget.remaining_budget_usd).model_dump_json()


@pytest.mark.parametrize("count", [2, 3])
def test_valid_batched_design_and_contradictory_context(ledger, project, count):
    result, designer, critic = run(ledger, project, limits=DesignLimits(candidate_count=count))
    assert len(result.candidate_ids) == count and len(result.review_ids) == count
    assert designer.calls == ['generate'] and critic.calls == ['initial']
    assert any('CONTRADICTING' in e['tags'] for e in designer.contexts[0].evidence)
    assert designer.contexts[0] == critic.contexts[0]
    assert not ledger.list_experiments(project.project_id)


@pytest.mark.parametrize("count", [0, 1, 4])
def test_candidate_count_configuration(count):
    with pytest.raises(ValidationError):
        DesignLimits(candidate_count=count)


@pytest.mark.parametrize("field,value", [("project_id", "PROJECT_OTHER"), ("hypothesis_id", "HYP_OTHER"),
    ("hypothesis_version", 2), ("version", 2), ("status", s.ExperimentStatus.SELECTED), ("objective", " "),
    ("approach", " "), ("expected_information_gain", None), ("feasibility_score", 1.1), ("major_risks", [])])
def test_malformed_candidate_rejected(ledger, project, field, value):
    context = build_context(load_snapshot(ledger, project.project_id))
    assignments = ExperimentDesignPipeline(ledger)._assign(context)
    output = proposals(context, assignments)
    output.candidates[0] = output.candidates[0].model_copy(update={field: value})
    with pytest.raises((ValidationError, ExperimentDesignError)):
        validate_candidates(output, context, assignments)


@pytest.mark.parametrize("field", ['primary_metric', 'success_criteria', 'falsification_criteria', 'controls',
    'independent_variables', 'dependent_variables', 'required_resources', 'required_capabilities',
    'potential_confounders', 'expected_result_patterns', 'inconclusive_criteria'])
def test_missing_preregistration_fields(ledger, project, field):
    context = build_context(load_snapshot(ledger, project.project_id))
    assignments = ExperimentDesignPipeline(ledger)._assign(context)
    output = proposals(context, assignments)
    output.candidates[0].design.pop(field)
    with pytest.raises(ExperimentDesignError):
        validate_candidates(output, context, assignments)


@pytest.mark.parametrize("change", ['empty_control', 'blank_capability', 'result', 'nested_result', 'code', 'bad_evidence', 'bad_pattern'])
def test_structural_and_result_leakage_rejected(ledger, project, change):
    context = build_context(load_snapshot(ledger, project.project_id))
    assignments = ExperimentDesignPipeline(ledger)._assign(context)
    output = proposals(context, assignments)
    d = output.candidates[0].design
    if change == 'empty_control': d['controls'] = {}
    if change == 'blank_capability': d['required_capabilities'] = [' ']
    if change == 'result': d['results'] = {'accuracy': 1}
    if change == 'nested_result': d['dependent_variables']['observed_results'] = 1
    if change == 'code': d['code'] = 'print(1)'
    if change == 'bad_evidence': d['evidence_ids'] = ['EVID_FAKE']
    if change == 'bad_pattern': d['expected_result_patterns'] = {'supported': 'better'}
    with pytest.raises((ValidationError, ExperimentDesignError)):
        validate_candidates(output, context, assignments)


@pytest.mark.parametrize("error", ['duplicate', 'foreign', 'malformed'])
def test_invalid_designer_bounded_no_candidate_persisted(ledger, project, error):
    designer = FakeDesigner(error)
    with pytest.raises(ExperimentDesignError):
        run(ledger, project, designer)
    assert designer.calls == ['generate']
    assert not ledger.list_experiment_candidates(project.project_id)
    assert any(e.event_type == 'EXPERIMENT_DESIGN_FAILED' for e in ledger.list_events(project.project_id))


def test_duplicate_against_prior_nonselected_design(ledger, project):
    run(ledger, project)
    with pytest.raises(ExperimentDesignError, match='already considered'):
        run(ledger, project)
    assert len(ledger.list_experiment_candidates(project.project_id)) == 2


@pytest.mark.parametrize("verdict", ['PASS', 'REVISE', 'REJECT', 'BLOCK'])
def test_verdicts_persist_exact_target_versions(ledger, project, verdict):
    result, _, _ = run(ledger, project, critic=FakeCritic([verdict]*2), limits=DesignLimits(max_revision_rounds=0))
    reviews = [r for r in ledger.list_reviews(project.project_id) if r.review_type == 'experiment']
    assert len(reviews) == 2 and all(r.verdict == verdict and r.target_version == 1 for r in reviews)
    latest = latest_versions(ledger.list_experiment_candidates(project.project_id), 'candidate_id')
    if verdict == 'REJECT':
        assert all(c.status == s.ExperimentStatus.CANCELLED and c.version == 2 for c in latest)
        assert len(result.rejected_candidate_ids) == 2
    else: assert all(c.version == 1 for c in latest)


@pytest.mark.parametrize("problem", ['Wrong primary metric unrelated to hypothesis', 'Missing fair baseline',
    'Target label encoded in constructed evaluation data', 'Redundant experiment differs only in sample size'])
def test_scientific_flaw_fixture_rejected_by_critic(ledger, project, problem):
    error = 'wrong_metric' if problem.startswith('Wrong') else ('leakage' if problem.startswith('Target') else None)
    result, _, _ = run(ledger, project, designer=FakeDesigner(error), critic=FakeCritic(['REJECT', 'PASS'], problem=problem))
    assert len(result.rejected_candidate_ids) == 1 and len(result.final_candidate_ids) == 1
    assert any(r.issues and r.issues[0]['problem'] == problem for r in ledger.list_reviews(project.project_id))


@pytest.mark.parametrize("error", ['malformed', 'target_id', 'target_version', 'target_type', 'review_type',
    'project_id', 'reviewer_role', 'review_id', 'citation', 'issues', 'duplicate'])
def test_invalid_critic_preserves_proposals_rejects_review(ledger, project, error):
    critic = FakeCritic(error=error)
    with pytest.raises(ExperimentDesignError): run(ledger, project, critic=critic)
    assert critic.calls == ['initial'] and len(ledger.list_experiment_candidates(project.project_id)) == 2
    assert not [r for r in ledger.list_reviews(project.project_id) if r.review_type == 'experiment']


@pytest.mark.parametrize("disposition", ['ACCEPT', 'REBUT', 'CLARIFY'])
@pytest.mark.parametrize("final", ['PASS', 'REVISE', 'REJECT', 'BLOCK'])
def test_one_revision_preserves_original_and_rebuttal_history(ledger, project, disposition, final):
    result, designer, critic = run(ledger, project, FakeDesigner(disposition=disposition), FakeCritic(['PASS', 'REVISE'], final=final))
    assert result.revision_rounds == 1 and designer.calls == ['generate', 'revise'] and critic.calls == ['initial', 'final']
    identifier = result.candidate_ids[1]
    old, new = ledger.get(s.ExperimentCandidate, identifier, version=1), ledger.get(s.ExperimentCandidate, identifier, version=2)
    assert old and new and old.design == new.design
    assert len([r for r in ledger.list_reviews(project.project_id) if r.target_id == identifier]) == 2
    event = next(e for e in ledger.list_events(project.project_id) if e.event_type == 'EXPERIMENT_CANDIDATE_REVISED')
    assert event.payload['responses'][0]['disposition'] == disposition
    if final == 'REJECT': assert ledger.get(s.ExperimentCandidate, identifier).version == 3


@pytest.mark.parametrize("error", ['revision', 'response'])
def test_bad_revision_preserves_valid_prior_history(ledger, project, error):
    with pytest.raises(ExperimentDesignError):
        run(ledger, project, FakeDesigner(error), FakeCritic(['REVISE', 'PASS']))
    assert len(ledger.list_experiment_candidates(project.project_id)) == 2
    assert len([r for r in ledger.list_reviews(project.project_id) if r.review_type == 'experiment']) == 2


def test_pause_during_critic_rejects_stale_output(ledger, project):
    def pause():
        ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'), project_id=project.project_id,
            event_type='PROJECT_PAUSED', actor='human', summary='Pause fixture'))
    with pytest.raises(ExperimentDesignError, match='blocked'):
        run(ledger, project, critic=FakeCritic(callback=pause))
    assert len(ledger.list_experiment_candidates(project.project_id)) == 2
    assert not [r for r in ledger.list_reviews(project.project_id) if r.review_type == 'experiment']


@pytest.mark.parametrize("kind", ['selection', 'review', 'evidence'])
def test_missing_selected_hypothesis_or_exact_review_fails(ledger, project, kind):
    snapshot = load_snapshot(ledger, project.project_id)
    if kind == 'selection': snapshot = snapshot.model_copy(update={'events': []})
    if kind == 'review': snapshot = snapshot.model_copy(update={'reviews': []})
    if kind == 'evidence': snapshot = snapshot.model_copy(update={'evidence': []})
    with pytest.raises(ExperimentDesignError): build_context(snapshot)


def test_context_is_bounded_before_calls(ledger, project):
    snapshot = load_snapshot(ledger, project.project_id)
    h = snapshot.hypotheses[0].model_copy(update={'rationale': 'x'*6000})
    snapshot = snapshot.model_copy(update={'hypotheses': [h]})
    with pytest.raises(ExperimentDesignError, match='bound'): build_context(snapshot, DesignLimits(max_context_chars=4000))


def test_real_adapters_use_omnigent_and_existing_critic(monkeypatch, ledger, project):
    context = build_context(load_snapshot(ledger, project.project_id))
    assignments = ExperimentDesignPipeline(ledger)._assign(context)
    designer, critic = OmnigentExperimentDesigner(), OmnigentScientificCritic()
    observed = []
    async def invoke(path, prompt, **kwargs):
        observed.append((path, json.loads(prompt), kwargs))
        data = json.loads(prompt)
        if kwargs['role'] == 'experiment_designer': return proposals(context, data['assigned_candidates']).model_dump_json()
        return (await FakeCritic().review_experiments(context, proposals(context, assignments).candidates, data['assigned_reviews'])).model_dump_json()
    monkeypatch.setattr(designer.transport, 'invoke_agent', invoke); monkeypatch.setattr(critic.transport, 'invoke_agent', invoke)
    run(ledger, project, designer, critic)
    assert [x[2]['role'] for x in observed] == ['experiment_designer', 'critic']
    assert observed[1][0].name == 'critic.yaml' and observed[1][1]['review_mode'] == 'experiment_design'
    design_schema = observed[0][1]['output_schema']['$defs']['ExperimentCandidate']['properties']['design']
    assert 'sampling_strategy' in design_schema['required'] and design_schema['additionalProperties'] is False


@pytest.mark.parametrize("role", ['designer', 'critic'])
def test_malformed_adapter_is_single_invocation(monkeypatch, ledger, project, role):
    designer, critic = OmnigentExperimentDesigner(), OmnigentScientificCritic()
    calls = []
    async def malformed(*args, **kwargs): calls.append(kwargs); return 'bad json'
    monkeypatch.setattr((designer if role == 'designer' else critic).transport, 'invoke_agent', malformed)
    with pytest.raises(ExperimentDesignError):
        run(ledger, project, designer if role == 'designer' else FakeDesigner(), critic if role == 'critic' else FakeCritic())
    assert len(calls) == 1


def test_planner_selects_lower_scored_candidate_and_preregisters_exactly_one(ledger, project):
    result, _, _ = run(ledger, project)
    planner = FakePlanner(choice=1)
    route = asyncio.run(Orchestrator(ledger, planner).decide(project.project_id))
    assert route.action == s.PlannerAction.SELECT_EXPERIMENT
    snapshot = load_snapshot(ledger, project.project_id)
    assert len(snapshot.experiments) == 1 and len(snapshot.candidates) == 2
    assert len(planner.contexts[0].summaries['candidates']) == 2
    experiment = selected_experiment(snapshot)
    candidate = ledger.get(s.ExperimentCandidate, result.candidate_ids[1])
    assert experiment.hypothesis_id == candidate.hypothesis_id and experiment.hypothesis_version == candidate.hypothesis_version
    for name in ('primary_metric', 'potential_confounders', 'required_resources', 'required_capabilities'):
        assert getattr(experiment, name) == candidate.design[name]
    for name in ('success_criteria', 'falsification_criteria', 'controls'):
        assert all(getattr(experiment, name)[k] == v for k, v in candidate.design[name].items())
    assert experiment.dataset_requirements['sampling_strategy'] == candidate.design['sampling_strategy']
    assert experiment.falsification_criteria['inconclusive_criteria'] == candidate.design['inconclusive_criteria']
    assert experiment.success_criteria['expected_result_patterns'] == candidate.design['expected_result_patterns']
    event = next(e for e in snapshot.events if e.event_type == 'EXPERIMENT_SELECTED')
    assert event.payload['candidate_id'] == candidate.candidate_id and event.payload['candidate_version'] == 1
    assert event.payload['decision_id'] == route.decision_id and event.payload['reason'] == route.reason
    assert event.payload['review_id'] in result.review_ids
    assert event.payload['non_selected_candidate_ids'] == [result.candidate_ids[0]]
    assert experiment.created_at > max(r.created_at for r in snapshot.reviews)
    assert not snapshot.resources and not snapshot.implementations and not snapshot.runs and not snapshot.metrics


@pytest.mark.parametrize("kind", ['ambiguous', 'missing', 'rejected', 'stale_review', 'wrong_hypothesis', 'invalid_design'])
def test_selection_invalid_candidate_rejected(ledger, project, kind):
    run(ledger, project)
    snapshot = load_snapshot(ledger, project.project_id)
    ids = [snapshot.candidates[0].candidate_id]
    if kind == 'ambiguous': ids = [c.candidate_id for c in snapshot.candidates]
    if kind == 'missing': ids = ['CAND_MISSING']
    if kind == 'rejected': snapshot.candidates[0] = snapshot.candidates[0].model_copy(update={'status': s.ExperimentStatus.CANCELLED})
    if kind == 'stale_review': snapshot.candidates[0] = snapshot.candidates[0].model_copy(update={'version': 2})
    if kind == 'wrong_hypothesis': snapshot.candidates[0] = snapshot.candidates[0].model_copy(update={'hypothesis_version': 2})
    if kind == 'invalid_design': snapshot.candidates[0].design.pop('primary_metric')
    decision = s.NextDecision(decision_id='DEC_FIXTURE', project_id=project.project_id, action=s.PlannerAction.SELECT_EXPERIMENT,
        target_agent='planner', reason='Select fixture', required_context_ids=ids, remaining_budget_usd=10)
    assert not DecisionValidator().validate(decision, snapshot).valid


def test_selection_cannot_repeat_and_spec_history_survives_restart(ledger, project):
    run(ledger, project)
    control = Orchestrator(ledger, FakePlanner())
    asyncio.run(control.decide(project.project_id))
    with pytest.raises(IllegalDecisionError): asyncio.run(control.decide(project.project_id))
    spec = ledger.list_experiments(project.project_id)[0]
    with pytest.raises(ValueError): ledger.add_experiment_spec(spec.model_copy(update={'primary_metric': 'silently altered'}))
    amendment = spec.model_copy(update={'version': 2, 'primary_metric': 'explicit later amendment', 'created_at': s.utc_now()})
    ledger.add_experiment_spec(amendment)
    with ResearchLedger(ledger.database.path) as reopened:
        assert reopened.get(s.ExperimentSpec, spec.experiment_id, version=1) == spec
        assert reopened.get(s.ExperimentSpec, spec.experiment_id, version=2) == amendment
        assert selected_experiment(load_snapshot(reopened, project.project_id)).version == 1


def test_orchestration_executes_registered_design_and_returns_to_pi(ledger, project):
    planner = FakePlanner(action=s.PlannerAction.DESIGN_EXPERIMENT)
    control = Orchestrator(ledger, planner)
    route = asyncio.run(control.decide(project.project_id))
    designer, critic = FakeDesigner(), FakeCritic()
    result = asyncio.run(control.execute_experiment_design(route, ExperimentDesignPipeline(ledger, designer, critic)))
    assert designer.calls == ['generate'] and critic.calls == ['initial']
    planner.action = s.PlannerAction.SELECT_EXPERIMENT
    asyncio.run(control.decide(project.project_id))
    assert len(planner.contexts) == 2 and len(ledger.list_experiments(project.project_id)) == 1
    snapshot = load_snapshot(ledger, project.project_id)
    assert any(e.event_type == 'SPECIALIST_COMPLETED' and e.payload['candidate_ids'] == result.candidate_ids for e in snapshot.events)
    assert not snapshot.resources and not snapshot.readiness and not snapshot.implementations and not snapshot.runs


@pytest.mark.parametrize("action", [s.PlannerAction.GATHER_EVIDENCE, s.PlannerAction.STOP])
def test_all_rejected_returns_to_pi_without_fabricating_spec(ledger, project, action):
    run(ledger, project, critic=FakeCritic(['REJECT', 'REJECT']))
    planner = FakePlanner(action=action)
    route = asyncio.run(Orchestrator(ledger, planner).decide(project.project_id))
    assert route.action == action and s.PlannerAction.SELECT_EXPERIMENT not in planner.contexts[0].available_actions
    assert all(c['critic']['verdict'] == 'REJECT' for c in planner.contexts[0].summaries['candidates'])
    assert not ledger.list_experiments(project.project_id)


def test_candidate_overwrite_and_sql_replace_blocked(ledger, project):
    run(ledger, project)
    candidate = ledger.list_experiment_candidates(project.project_id)[0]
    with pytest.raises(ValueError): ledger.add_experiment_candidate(candidate)
    conn = ledger.database.connection
    with pytest.raises(sqlite3.IntegrityError): conn.execute('INSERT OR REPLACE INTO experiment_candidates SELECT * FROM experiment_candidates LIMIT 1')
    with pytest.raises(sqlite3.IntegrityError): conn.execute('DELETE FROM experiment_candidates')


def test_candidate_review_certifies_only_identical_preregistered_projection(ledger, project):
    run(ledger, project)
    asyncio.run(Orchestrator(ledger, FakePlanner()).decide(project.project_id))
    snapshot = load_snapshot(ledger, project.project_id)
    spec = selected_experiment(snapshot)
    review = latest_review(snapshot, s.ExperimentSpec, spec.experiment_id, spec.version)
    assert review and review.target_type == 'experiment_candidates'
    assert derive_control_state(snapshot).value == 'AWAITING_HUMAN_APPROVAL'
    assert len([r for r in snapshot.reviews if r.target_type == 'experiments']) == 0
    altered = spec.model_copy(update={'primary_metric': 'changed after selection'})
    modified = snapshot.model_copy(update={'experiments': [altered]})
    assert latest_review(modified, s.ExperimentSpec, spec.experiment_id, spec.version) is None
    assert derive_control_state(modified).value == 'EXPERIMENT_REVIEW'


def test_unknown_estimates_cannot_authorize_future_consequential_work(ledger, project):
    run(ledger, project)
    asyncio.run(Orchestrator(ledger, FakePlanner()).decide(project.project_id))
    snapshot = load_snapshot(ledger, project.project_id)
    spec = selected_experiment(snapshot)
    ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'), project_id=project.project_id,
        event_type='HUMAN_APPROVED', actor='human', summary='Offline hypothetical later-phase approval',
        payload={'experiment_id': spec.experiment_id, 'experiment_version': 1,
            'approved_actions': ['PREPARE_RESOURCES'], 'max_cost_usd': 10, 'max_runtime_minutes': 60}))
    decision = s.NextDecision(decision_id='DEC_FUTURE', project_id=project.project_id, action='PREPARE_RESOURCES',
        target_agent='preparation', reason='Hypothetical future action', remaining_budget_usd=10)
    result = DecisionValidator().validate(decision, load_snapshot(ledger, project.project_id))
    assert result.status.value == 'NEEDS_HUMAN_APPROVAL' and 'current feasibility assessment' in result.reasons[0]


def test_completed_route_cannot_repeat(ledger, project):
    control = Orchestrator(ledger, FakePlanner(action=s.PlannerAction.DESIGN_EXPERIMENT))
    route = asyncio.run(control.decide(project.project_id))
    workflow = ExperimentDesignPipeline(ledger, FakeDesigner(), FakeCritic())
    asyncio.run(control.execute_experiment_design(route, workflow))
    with pytest.raises(IllegalDecisionError, match='already completed'):
        asyncio.run(control.execute_experiment_design(route, workflow))


def test_no_second_active_contract_for_nonselected_candidate(ledger, project):
    run(ledger, project)
    asyncio.run(Orchestrator(ledger, FakePlanner(choice=0)).decide(project.project_id))
    snapshot = load_snapshot(ledger, project.project_id)
    decision = s.NextDecision(decision_id='DEC_SECOND', project_id=project.project_id, action='SELECT_EXPERIMENT', target_agent='planner',
        reason='Attempt another simultaneous contract', required_context_ids=[snapshot.candidates[1].candidate_id], remaining_budget_usd=10)
    assert not DecisionValidator().validate(decision, snapshot).valid
    assert len(snapshot.experiments) == 1


def test_conflicting_proposal_details_cannot_be_overwritten(ledger, project):
    context = build_context(load_snapshot(ledger, project.project_id))
    assignments = ExperimentDesignPipeline(ledger)._assign(context)
    output = proposals(context, assignments)
    candidate = output.candidates[0]
    candidate.design['dataset_requirements']['sampling_strategy'] = 'inconsistent alternative sampling'
    with pytest.raises(ExperimentDesignError, match='Conflicting'):
        spec_from_candidate(candidate, 'EXP_NEW')


def test_future_design_context_retains_rejection_and_nonselection_reasons(ledger, project):
    result, _, _ = run(ledger, project, critic=FakeCritic(['REJECT', 'PASS']))
    asyncio.run(Orchestrator(ledger, FakePlanner(choice=1)).decide(project.project_id))
    context = build_context(load_snapshot(ledger, project.project_id))
    rejected = next(c for c in context.previous_candidates if c['id'] == result.candidate_ids[0])
    selected = next(c for c in context.previous_candidates if c['id'] == result.candidate_ids[1])
    assert rejected['status'] == 'CANCELLED' and rejected['critic']['verdict'] == 'REJECT'
    assert rejected['critic']['reviewed_version'] == 1 and rejected['version'] == 2
    assert rejected['critic']['concerns'][0]['problem'] and selected['selected_experiment_id'] == 'EXP_0001'


def test_v1_ledger_migration_preserves_json_ids_and_review(tmp_path):
    # Construct the actual Phase 2 candidate layout, including immutable guards.
    from autolab.ledger.database import LedgerDatabase
    path = tmp_path/'legacy.db'
    with ResearchLedger(path) as old:
        p = old.create_project(s.ResearchCharter(project_id='PROJECT_1', title='Old', research_question='Old?', objective='Old', primary_outcome='Old'))
        h = old.add_hypothesis(s.Hypothesis(hypothesis_id='HYP_1', project_id=p.project_id, statement='Old', falsifiable_prediction='Old'))
        candidate = old.add_experiment_candidate(s.ExperimentCandidate(candidate_id='CAND_1', project_id=p.project_id, hypothesis_id=h.hypothesis_id, title='Old', objective='Old', approach='Old'))
        review = old.add_review(s.ReviewRecord(review_id='ERREV_1', project_id=p.project_id, review_type='experiment', target_type='experiment_candidates', target_id=candidate.candidate_id, verdict='PASS', reviewer_role='critic'))
        conn = old.database.connection
        payload = json.loads(conn.execute('SELECT record_json FROM experiment_candidates').fetchone()[0]); payload.pop('design'); payload.pop('version')
        for suffix in ('no_replace', 'no_update', 'no_delete'): conn.execute(f'DROP TRIGGER experiment_candidates_{suffix}')
        conn.execute('DROP TABLE experiment_candidates')
        conn.execute('CREATE TABLE experiment_candidates (created_at TEXT NOT NULL, record_json TEXT NOT NULL, candidate_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id), hypothesis_id TEXT NOT NULL, hypothesis_version INTEGER NOT NULL, FOREIGN KEY(hypothesis_id,hypothesis_version,project_id) REFERENCES hypotheses(hypothesis_id,version,project_id))')
        conn.execute('INSERT INTO experiment_candidates VALUES(?,?,?,?,?,?)', (candidate.created_at.isoformat(), json.dumps(payload), candidate.candidate_id, p.project_id, h.hypothesis_id, 1))
        for statement in LedgerDatabase._immutable_triggers('experiment_candidates', ('candidate_id',)): conn.execute(statement)
        conn.execute('PRAGMA user_version=1')
    with ResearchLedger(path) as upgraded:
        assert upgraded.get(s.ExperimentCandidate, 'CAND_1') == candidate
        assert upgraded.get(s.ReviewRecord, 'ERREV_1') == review
        assert json.loads(upgraded.database.connection.execute('SELECT record_json FROM experiment_candidates').fetchone()[0]) == payload
        upgraded.add_experiment_candidate(candidate.model_copy(update={'version': 2, 'approach': 'Explicit revision'}))
        upgraded.initialize()
        assert upgraded.get(s.ExperimentCandidate, 'CAND_1').version == 2
        assert upgraded.database.connection.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('reference', ['candidate', 'hypothesis', 'foreign'])
def test_design_critique_references_only_supplied_scientific_artifacts(ledger, project, reference):
    from autolab.experiment_design.validation import validate_reviews
    context=build_context(load_snapshot(ledger,project.project_id))
    assignments=[{'candidate_id':f'CAND_TEST_{i}','version':1,'project_id':project.project_id,
        'hypothesis_id':context.hypothesis.hypothesis_id,'hypothesis_version':context.hypothesis.version} for i in range(2)]
    candidates=proposals(context,assignments).candidates
    reviews=[{'review_id':f'ERREV_TEST_{i}','project_id':project.project_id,
        'target_id':c.candidate_id,'target_version':c.version} for i,c in enumerate(candidates)]
    batch=asyncio.run(FakeCritic(verdicts=['REVISE','PASS']).review_experiments(context,candidates,reviews))
    batch.reviews[0].issues[0]['evidence_ids']=[candidates[0].candidate_id if reference=='candidate'
        else context.hypothesis.hypothesis_id if reference=='hypothesis' else 'CAND_FOREIGN']
    if reference=='foreign':
        with pytest.raises(ExperimentDesignError,match='unavailable evidence'):
            validate_reviews(batch,candidates,context,reviews)
    else:
        assert validate_reviews(batch,candidates,context,reviews).reviews[0].verdict==s.ReviewVerdict.REVISE


def test_explicit_review_recovery_never_regenerates_or_repeats_valid_reviews(ledger,project):
    designer=FakeDesigner()
    critic=FakeCritic(error='malformed')
    pipeline=ExperimentDesignPipeline(ledger,designer,critic)
    with pytest.raises(ExperimentDesignError):
        asyncio.run(pipeline.generate(project.project_id))
    candidates=ledger.list_experiment_candidates(project.project_id)
    assert len(candidates)==2 and not any(r.review_type=='experiment' for r in ledger.list_reviews(project.project_id))
    critic.error=None
    result=asyncio.run(pipeline.review_existing(project.project_id))
    assert len(result.final_candidate_ids)==2 and designer.calls==['generate']
    assert ledger.list_experiment_candidates(project.project_id)==candidates
    before=ledger.list_reviews(project.project_id)
    with pytest.raises(ExperimentDesignError,match='no successful work'):
        asyncio.run(pipeline.review_existing(project.project_id))
    assert ledger.list_reviews(project.project_id)==before and critic.calls==['initial','initial']
    assert any(e.event_type=='EXPERIMENT_DESIGN_FAILED' for e in ledger.list_events(project.project_id))


def test_review_recovery_preserves_existing_one_revision_bound(ledger,project):
    designer=FakeDesigner()
    critic=FakeCritic(error='malformed',verdicts=['REVISE','PASS'],final='REVISE')
    pipeline=ExperimentDesignPipeline(ledger,designer,critic)
    with pytest.raises(ExperimentDesignError):
        asyncio.run(pipeline.generate(project.project_id))
    critic.error=None
    result=asyncio.run(pipeline.review_existing(project.project_id))
    assert result.revision_rounds==1 and designer.calls==['generate','revise']
    with pytest.raises(ExperimentDesignError):
        asyncio.run(pipeline.review_existing(project.project_id))
    assert designer.calls==['generate','revise']


def test_recovery_cannot_reopen_loop_after_failed_final_revision_review(ledger,project):
    class FailedFinalCritic(FakeCritic):
        async def review_experiments(self,*args,responses=None,**kwargs):
            if responses is not None:
                raise ExperimentDesignError('Explicit simulated final review failure')
            return await super().review_experiments(*args,responses=responses,**kwargs)
    designer=FakeDesigner();critic=FailedFinalCritic(verdicts=['REVISE','REVISE'])
    pipeline=ExperimentDesignPipeline(ledger,designer,critic)
    with pytest.raises(ExperimentDesignError):asyncio.run(pipeline.generate(project.project_id))
    assert designer.calls==['generate','revise']
    with pytest.raises(ExperimentDesignError,match='no successful work'):
        asyncio.run(pipeline.review_existing(project.project_id))
    assert designer.calls==['generate','revise']
