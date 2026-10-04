"""Offline scientific interpretation, independent critique and integrity tests."""
import asyncio
import json
import math
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import current_analysis, current_run, selected_experiment, derive_control_state
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.budget import calculate_budget
from autolab.orchestration.orchestrator import Orchestrator, IllegalDecisionError
from autolab.orchestration.models import RoutingDecision
from autolab.preparation.manifest import fingerprint
from autolab.analysis.models import AnalysisError, AnalysisOutput, ResultSummary
from autolab.analysis.result_summary import build_result_summary, evidence_pins, comparison_contract
from autolab.analysis.validation import validate_analysis, scientific_findings, validate_responses
from autolab.analysis.persistence import analysis_current, reviewed_analysis
from autolab.analysis.service import AnalysisService
from autolab.hypotheses.models import ReviewBatch, CritiqueResponse
from test_runtime import ready_runtime, replace_implementation
from autolab.runtime_smoke_helpers import PROJECT


def run(coro):return asyncio.run(coro)

@pytest.fixture
def completed(ready_runtime):
    runtime,_,_=ready_runtime
    record=run(runtime.run(PROJECT));assert record.status=='COMPLETED'
    return runtime.ledger

def snapshot(ledger):return load_snapshot(ledger,PROJECT)


def analysis_output(context,assignment,*,assessment=None):
    summary=ResultSummary.model_validate(context['result_summary'])
    assessment=assessment or ('SUPPORTED' if summary.criteria['success_met'] else 'NOT_SUPPORTED' if summary.criteria['falsification_met'] else 'INCONCLUSIVE')
    metrics=summary.metrics
    a=s.ScientificAnalysis(**assignment,project_id=summary.project_id,experiment_id=summary.experiment_id,
        experiment_version=summary.experiment_version,run_id=summary.run_id,hypothesis_id=summary.hypothesis_id,
        hypothesis_version=summary.hypothesis_version,metric_ids=[m['metric_id'] for m in metrics],evidence_pins=summary.pins,
        criteria_evaluation=summary.criteria,hypothesis_assessment=assessment,
        interpretation='Observed condition comparison satisfies the descriptive preregistered criterion within this fixed fixture only.',
        key_findings=[m['condition']+' observed '+m['name']+' '+str(m['value']) for m in metrics],
        limitations=summary.limitations or ['Comparison is confined to fixed inputs'],
        confounders=[{'confounder':c,'status':'POTENTIALLY_ACTIVE','evidence':'The bounded fixed-input comparison does not establish external validity'} for c in context['experiment_spec']['potential_confounders']],
        claims=[{'claim':'Observed '+m['condition']+' metric','level':'OBSERVATION','evidence_ids':[m['metric_id'],summary.run_id],
            'values':{m['metric_id']:m['value']}} for m in metrics],
        causal_scope='Descriptive matched comparison only',generalization_scope='No generalization outside supplied fixed inputs')
    return AnalysisOutput(analysis=a)

class Analyst:
    def __init__(self,mutate=None,disposition='ACCEPT',failure=False):self.calls=0;self.mutate=mutate;self.disposition=disposition;self.failure=failure
    async def interpret(self,context,assignment,*,previous=None,review=None):
        self.calls+=1
        if self.failure:raise RuntimeError('Offline model failure')
        out=analysis_output(context,assignment)
        if self.mutate:out=self.mutate(out,previous)
        if review:
            summary=ResultSummary.model_validate(context['result_summary'])
            out=out.model_copy(update={'responses':[CritiqueResponse(review_id=review.review_id,issue_index=i,
                disposition=self.disposition,reason='Bounded evidence-supported correction or explanation',evidence_ids=[summary.run_id]) for i in range(len(review.issues))]})
        return out

class Critic:
    def __init__(self,sequence=None,mutate=None,failure=False):self.calls=0;self.sequence=sequence or ['PASS'];self.mutate=mutate;self.failure=failure
    async def review_analysis(self,context,a,assignment,*,findings=None,responses=None):
        self.calls+=1
        if self.failure:raise RuntimeError('Offline independent model failure')
        verdict=self.sequence[min(self.calls-1,len(self.sequence)-1)]
        issues=findings or ([{'problem':'Clarify fixture representativeness','severity':'medium','section':'limitations',
            'evidence_ids':[a.run_id],'why_it_matters':'Fixed inputs constrain inference','resolution':'State fixed-input scope explicitly'}] if verdict!='PASS' else [])
        if findings and verdict=='PASS':verdict='REVISE'
        r=s.ReviewRecord(**assignment,review_type='analysis',target_type='analyses',reviewer_role='critic',verdict=verdict,issues=issues)
        if self.mutate:r=self.mutate(r)
        return ReviewBatch(reviews=[r])

def service(ledger,agent=None,critic=None):return AnalysisService(ledger,agent or Analyst(),critic or Critic())


def test_summary_deterministic_values_counts_differences_and_no_model(completed):
    summary=build_result_summary(snapshot(completed));other=build_result_summary(snapshot(completed))
    assert summary==other and summary.statistics=='Descriptive only'
    values={m['condition']:m['value'] for m in summary.metrics}
    assert values['baseline']==pytest.approx(.175) and values['clipped']==pytest.approx(.075)
    assert all(c['observations']==4 and c['unique_samples']==4 and c['success_count']==4 and c['failure_count']==0 and c['missing_sample_count']==0 for c in summary.conditions)
    diff=summary.differences[0]
    assert diff['intervention_minus_control']==pytest.approx(-.1) and diff['absolute_difference']==pytest.approx(.1)
    assert diff['relative_difference']==pytest.approx(-4/7) and diff['direction']=='lower'
    assert summary.criteria['success_met'] is True and summary.criteria['falsification_met'] is False
    assert summary.actual_cost_usd is None and summary.actual_cost_status=='UNKNOWN' and summary.usage['calls']==8
    assert 'p_value' not in summary.model_dump()

@pytest.mark.parametrize('status',['FAILED','TIMED_OUT','CANCELLED','PENDING','RUNNING'])
def test_analysis_rejects_noncompleted(completed,status):
    snap=snapshot(completed);r=current_run(snap)
    with pytest.raises(AnalysisError):build_result_summary(snap.model_copy(update={'runs':[r.model_copy(update={'status':status})]}))

@pytest.mark.parametrize('damage',['primary','wrong_run','raw','metric','run','spec','hypothesis'])
def test_preconditions_reject_integrity_or_dependency_damage(completed,damage):
    snap=snapshot(completed)
    if damage=='primary':snap=snap.model_copy(update={'metrics':snap.metrics[1:]})
    if damage=='wrong_run':snap=snap.model_copy(update={'metrics':[m.model_copy(update={'run_id':'RUN_WRONG'}) for m in snap.metrics]})
    if damage=='raw':Path(current_run(snap).output_manifest['artifacts']['raw_outputs.jsonl']['path']).write_text('{}\n')
    if damage=='metric':snap=snap.model_copy(update={'metrics':[m.model_copy(update={'metric_value':999.}) for m in snap.metrics]})
    if damage=='run':snap=snap.model_copy(update={'runs':[current_run(snap).model_copy(update={'random_seed':123})]})
    if damage=='spec':snap=snap.model_copy(update={'experiments':[*snap.experiments,selected_experiment(snap).model_copy(update={'version':2})]})
    if damage=='hypothesis':snap=snap.model_copy(update={'hypotheses':[*snap.hypotheses,snap.hypotheses[0].model_copy(update={'version':2})]})
    with pytest.raises(AnalysisError):build_result_summary(snap)


def test_structured_analysis_pins_criteria_confounds_trace_and_planner_context(completed):
    workflow=service(completed)
    a=run(workflow.analyze(PROJECT));snap=snapshot(completed)
    assert a.version==1 and a.hypothesis_id==selected_experiment(snap).hypothesis_id and a.hypothesis_version==1
    assert a.run_id==current_run(snap).run_id and a.experiment_version==1 and a.metric_ids==[m.metric_id for m in snap.metrics]
    assert a.criteria_evaluation['success_met'] and a.limitations and a.confounders
    assert analysis_current(snap,a) and not reviewed_analysis(snap)
    assert derive_control_state(snap)=='ANALYSIS_REVIEW'
    claim=a.claims[0];metric=next(m for m in snap.metrics if m.metric_id==claim['evidence_ids'][0])
    r=completed.get_run(metric.run_id)
    assert metric.metadata['raw_sha256']==r.output_manifest['artifacts']['raw_outputs.jsonl']['sha256']==a.evidence_pins['raw_sha256']
    ctx=ContextBuilder().build(snap).current_records['analysis']
    assert ctx['version']==1 and ctx['fresh'] and ctx['run_id']==r.run_id and ctx['critic_verdict'] is None

@pytest.mark.parametrize('field,value',[('run_id','RUN_FAKE'),('experiment_version',2),('hypothesis_id','HYP_FAKE'),('hypothesis_version',2),('metric_ids',['METRIC_FAKE']),('evidence_pins',{}),('criteria_evaluation',{}),('version',3),('confidence',.8),('recommended_followup',['Run new experiment'])])
def test_analysis_rejects_wrong_identity_or_invented_contract(completed,field,value):
    agent=Analyst(mutate=lambda out,previous:out.model_copy(update={'analysis':out.analysis.model_copy(update={field:value})}))
    with pytest.raises(AnalysisError):run(service(completed,agent).analyze(PROJECT))
    assert not snapshot(completed).analyses and agent.calls==1

@pytest.mark.parametrize('claim',[{'claim':'fake','level':'OBSERVATION','evidence_ids':['METRIC_FAKE']},
    {'claim':'fake','level':'OBSERVATION','evidence_ids':['METRIC_0001'],'values':{'METRIC_0001':42.}},
    {'claim':'fake','level':'UNIVERSAL','evidence_ids':['RUN_0001']}])
def test_imaginary_claim_reference_or_value_rejected(completed,claim):
    agent=Analyst(mutate=lambda out,previous:out.model_copy(update={'analysis':out.analysis.model_copy(update={'claims':[claim]})}))
    with pytest.raises(AnalysisError):run(service(completed,agent).analyze(PROJECT))

@pytest.mark.parametrize('verdict',['PASS','REVISE','REJECT'])
def test_independent_verdicts_persist_and_revision_bound(completed,verdict):
    workflow=service(completed,critic=Critic([verdict]));result=run(workflow.run(PROJECT));snap=snapshot(completed)
    assert result.verdict==verdict and result.phase12_executed is False and result.planner_control
    assert result.revision_rounds==(1 if verdict=='REVISE' else 0)
    assert workflow.agent.calls==(2 if verdict=='REVISE' else 1) and workflow.critic.calls==(2 if verdict=='REVISE' else 1)
    assert len(snap.analyses)==(2 if verdict=='REVISE' else 1)
    assert len([r for r in snap.reviews if r.review_type=='analysis'])==len(result.review_ids)
    if verdict=='PASS':assert reviewed_analysis(snap) and derive_control_state(snap)=='ADAPTIVE_DECISION'
    else:assert not reviewed_analysis(snap) and derive_control_state(snap)=='ADAPTIVE_DECISION'
    with pytest.raises(AnalysisError):run(workflow.critique(PROJECT))
    with pytest.raises(AnalysisError):run(workflow.analyze(PROJECT))

@pytest.mark.parametrize('disposition',['ACCEPT','REBUT','CLARIFY'])
def test_revision_responses_and_original_versions_preserved(completed,disposition):
    workflow=service(completed,agent=Analyst(disposition=disposition),critic=Critic(['REVISE','PASS']))
    result=run(workflow.run(PROJECT));snap=snapshot(completed)
    assert result.version==2 and result.revision_rounds==1 and reviewed_analysis(snap)
    assert [a.version for a in snap.analyses]==[1,2]
    assert completed.get(s.ScientificAnalysis,result.analysis_id,version=1)==snap.analyses[0]
    reviews=[r for r in snap.reviews if r.review_type=='analysis'];assert [r.target_version for r in reviews]==[1,2]
    event=next(e for e in snap.events if e.event_type=='SCIENTIFIC_ANALYSIS_REVISED')
    assert event.payload['responses'][0]['disposition']==disposition
    with pytest.raises(ValueError):completed.add_analysis(snap.analyses[0])

@pytest.mark.parametrize('damage',['raw','metric','run','spec','hypothesis'])
def test_stale_review_never_authorizes_downstream(completed,damage):
    run(service(completed).run(PROJECT));snap=snapshot(completed);assert reviewed_analysis(snap)
    if damage=='raw':Path(current_run(snap).output_manifest['artifacts']['raw_outputs.jsonl']['path']).write_text('tampered')
    if damage=='metric':snap=snap.model_copy(update={'metrics':[m.model_copy(update={'metric_value':99.}) for m in snap.metrics]})
    if damage=='run':snap=snap.model_copy(update={'runs':[current_run(snap).model_copy(update={'random_seed':99})]})
    if damage=='spec':snap=snap.model_copy(update={'experiments':[*snap.experiments,selected_experiment(snap).model_copy(update={'version':2})]})
    if damage=='hypothesis':snap=snap.model_copy(update={'hypotheses':[*snap.hypotheses,snap.hypotheses[0].model_copy(update={'version':2})]})
    assert not analysis_current(snap,current_analysis(snap)) and not reviewed_analysis(snap)
    for action,target in [('ACCEPT_HYPOTHESIS','planner'),('REJECT_HYPOTHESIS','planner'),('RUN_FOLLOWUP','experiment_designer')]:
        d=s.NextDecision(decision_id='DEC_GATE',project_id=PROJECT,action=action,target_agent=target,reason='Check stale gate',remaining_budget_usd=calculate_budget(snap).remaining_budget_usd)
        assert not DecisionValidator().validate(d,snap).valid

@pytest.mark.parametrize('violation,updates',[('overgeneralization',{'interpretation':'This experiment proves the intervention is universally superior.'}),
    ('unsupported_statistics',{'interpretation':'The result is statistically significant.'}),
    ('wrong_direction',{'interpretation':'baseline is better than clipped.'}),
    ('wrong_direction',{'interpretation':'0.175 is better than 0.075'}),
    ('unsupported_number',{'interpretation':'Observed MAE is 999.5'}),
    ('missing_limitations',{'limitations':[]}),('missing_confounder',{'confounders':[]}),
    ('unlabeled_exploration',{'unexpected_findings':['new pattern']}),('missing_trace',{'claims':[]})])
def test_scientific_guards_independent_critic_repairs_overclaim(completed,violation,updates):
    agent=Analyst(mutate=lambda out,previous:out if previous else out.model_copy(update={'analysis':out.analysis.model_copy(update=updates)}))
    workflow=service(completed,agent=agent)
    result=run(workflow.run(PROJECT));snap=snapshot(completed)
    first=next(r for r in snap.reviews if r.review_type=='analysis')
    assert any(i['why_it_matters']==violation for i in first.issues)
    assert first.verdict=='REVISE' and result.verdict=='PASS' and result.revision_rounds==1


def test_unsupported_causality_detected(completed):
    workflow=service(completed);a=run(workflow.analyze(PROJECT));snap=snapshot(completed);summary=build_result_summary(snap)
    a=a.model_copy(update={'causal_scope':'Clipping causes population improvement'})
    spec=selected_experiment(snap).model_copy(update={'controls':{}})
    assert any(i['why_it_matters']=='unsupported_causality' for i in scientific_findings(a,summary,spec))


def test_explicit_exploratory_findings_allowed(completed):
    agent=Analyst(mutate=lambda out,p:out.model_copy(update={'analysis':out.analysis.model_copy(update={'unexpected_findings':['Exploratory observation: identical fixed inputs were used in both conditions']})}))
    assert run(service(completed,agent).run(PROJECT)).verdict=='PASS'

@pytest.mark.parametrize('assessment',['SUPPORTED','NOT_SUPPORTED','INCONCLUSIVE'])
def test_assessment_paths_conservative(completed,assessment):
    snap=snapshot(completed);summary=build_result_summary(snap)
    criteria={**summary.criteria,'success_met':assessment=='SUPPORTED','falsification_met':assessment=='NOT_SUPPORTED'}
    if assessment=='INCONCLUSIVE':criteria['success_met']=criteria['falsification_met']=None
    summary=summary.model_copy(update={'criteria':criteria})
    context=AnalysisService._context(snap,summary);a=analysis_output(context,{'analysis_id':'ANALYSIS_FIXTURE','version':1},assessment=assessment).analysis
    assert not scientific_findings(a,summary,selected_experiment(snap)) and a.hypothesis_assessment==assessment


def test_null_result_real_completed_run_not_workflow_failure(ready_runtime):
    # Identity-only fixture transformation sets every frozen prediction within range;
    # scientific null follows real deterministic execution, not a completed label.
    from autolab.implementation_smoke_helpers import seed_fixture
    from autolab.implementation.service import ImplementationService
    from autolab.feasibility.persistence import spec_fingerprint
    from autolab.runtime.adapters import ScalarFixtureAdapter
    from autolab.runtime.service import ExperimentRuntime
    from autolab.runtime_smoke_helpers import authorize_execution
    from autolab.orchestration.state_machine import current_implementation
    from phase9_helpers import Implementer,Auditor
    with ResearchLedger(':memory:') as ledger:
        root=Path(ready_runtime[0].root)/'null-scientific'
        rows=[{'sample_id':f'toy-{i}','prediction':.2+i*.1,'target':.3+i*.1} for i in range(4)]
        _,spec,contract=run(seed_fixture(ledger,root,project_id=PROJECT,experiment_id='EXP_PHASE10',execution_fixture=True,resource_rows=rows))
        code=ImplementationService(ledger,Implementer(mutate_source=lambda files:{n:v.replace('EXP_PHASE9','EXP_PHASE10') for n,v in files.items()}),Auditor(),root=root,contracts={spec_fingerprint(spec):contract})
        assert run(code.run(PROJECT)).status=='READY'
        authorize_execution(ledger,current_implementation(snapshot(ledger)))
        runtime=ExperimentRuntime(ledger,root=root,adapters={spec_fingerprint(spec):ScalarFixtureAdapter(spec_fingerprint(spec))})
        assert run(runtime.run(PROJECT)).status=='COMPLETED'
        summary=build_result_summary(snapshot(ledger));assert summary.differences[0]['improvement']==0 and summary.criteria['falsification_met']
        result=run(service(ledger).run(PROJECT))
        assert result.verdict=='PASS' and current_analysis(snapshot(ledger)).hypothesis_assessment=='NOT_SUPPORTED'


def test_inconclusive_unresolved_confound_preserved(completed):
    agent=Analyst(mutate=lambda out,p:out.model_copy(update={'analysis':out.analysis.model_copy(update={'hypothesis_assessment':s.HypothesisAssessment.INCONCLUSIVE,
        'remaining_uncertainties':['Resource representativeness remains unresolved'],
        'confounders':[{'confounder':'Small fixture cannot establish generalization','status':'UNKNOWN','evidence':'No population sampling evidence'}]})}))
    result=run(service(completed,agent).run(PROJECT));assert result.verdict=='PASS'
    assert current_analysis(snapshot(completed)).hypothesis_assessment=='INCONCLUSIVE'

@pytest.mark.parametrize('actor',['analyst','critic'])
def test_model_failure_preserves_ledger_and_evidence(completed,actor):
    before=snapshot(completed)
    workflow=service(completed,Analyst(failure=actor=='analyst'),Critic(failure=actor=='critic'))
    with pytest.raises(RuntimeError):run(workflow.run(PROJECT))
    after=snapshot(completed)
    for field in ('runs','metrics','hypotheses','experiments','resources','implementations'):assert getattr(before,field)==getattr(after,field)
    assert not any(r.review_type=='analysis' for r in after.reviews)
    assert len(after.analyses)==(1 if actor=='critic' else 0)

@pytest.mark.parametrize('actor',['analyst','critic'])
def test_malformed_output_bounded(completed,actor):
    agent=Analyst(mutate=lambda out,p:{} if actor=='analyst' else out)
    critic=Critic(mutate=lambda r:r.model_copy(update={'target_version':7}) if actor=='critic' else r)
    with pytest.raises(AnalysisError):run(service(completed,agent,critic).run(PROJECT))
    assert agent.calls==1 and critic.calls==(1 if actor=='critic' else 0)


def test_orchestrator_route_calls_both_roles_once_and_returns_planner(completed):
    class Planner:
        calls=0
        async def propose(self,context,decision_id,feedback=None):
            self.calls+=1
            return s.NextDecision(decision_id=decision_id,project_id=PROJECT,action='ANALYZE_RESULT',target_agent='analyst',reason='Interpret completed run',remaining_budget_usd=context.budget.remaining_budget_usd).model_dump_json()
    orch=Orchestrator(completed,Planner());workflow=service(completed)
    route=run(orch.decide(PROJECT));result=run(orch.execute_analysis(route,workflow))
    assert result.planner_control and result.phase12_executed is False and orch.planner.calls==1
    assert workflow.agent.calls==workflow.critic.calls==1 and len(snapshot(completed).runs)==1
    assert any(e.event_type=='SPECIALIST_COMPLETED' and e.payload.get('role')=='analyst' for e in snapshot(completed).events)
    with pytest.raises(IllegalDecisionError):run(orch.execute_analysis(route,workflow))


def test_pass_cannot_override_deterministic_violation(completed):
    analyst=Analyst(mutate=lambda out,p:out.model_copy(update={'analysis':out.analysis.model_copy(update={'interpretation':'Universally superior and statistically significant'})}))
    critic=Critic(mutate=lambda r:r.model_copy(update={'verdict':s.ReviewVerdict.PASS,'issues':[]}))
    with pytest.raises(AnalysisError,match='PASS cannot'):run(service(completed,analyst,critic).run(PROJECT))
    assert not reviewed_analysis(snapshot(completed))


def test_no_unreviewed_analysis_authorizes_result_decision(completed):
    run(service(completed).analyze(PROJECT));snap=snapshot(completed)
    for action,target in [('RUN_FOLLOWUP','experiment_designer'),('ACCEPT_HYPOTHESIS','planner'),('REJECT_HYPOTHESIS','planner')]:
        decision=s.NextDecision(decision_id='DEC_GATE',project_id=PROJECT,action=action,target_agent=target,reason='Result decision gate',remaining_budget_usd=calculate_budget(snap).remaining_budget_usd)
        assert not DecisionValidator().validate(decision,snap).valid


def test_failed_sample_counts_preserved_in_explicit_mock_receipt(completed):
    # Offline receipt fixture only: simulate a different adapter whose frozen
    # failure policy includes a failed sample in its denominator. No production
    # metric/result admission is relaxed.
    snap=snapshot(completed);r=current_run(snap);pins=r.output_manifest['artifacts']
    raw_path=Path(pins['raw_outputs.jsonl']['path'])
    raw=[json.loads(line) for line in raw_path.read_text().splitlines()]
    raw[0]['observation']['status']='failure';raw[0]['observation']['failure_category']='controlled_failure'
    data=''.join(json.dumps(x)+'\n' for x in raw).encode();raw_path.write_bytes(data)
    from autolab.runtime.persistence import digest
    artifacts={**pins,'raw_outputs.jsonl':{**pins['raw_outputs.jsonl'],'size':len(data),'sha256':digest(data)}}
    metrics=[m.model_copy(update={'metadata':{**m.metadata,'raw_sha256':digest(data),'failure_policy':'failed attempts included in frozen denominator'}}) for m in snap.metrics]
    metric_path=Path(artifacts['metrics.json']['path']);metric_data=json.dumps([m.model_dump(mode='json') for m in metrics]).encode();metric_path.write_bytes(metric_data)
    artifacts['metrics.json']={**artifacts['metrics.json'],'size':len(metric_data),'sha256':digest(metric_data)}
    r=r.model_copy(update={'output_manifest':{**r.output_manifest,'artifacts':artifacts}})
    events=[e.model_copy(update={'payload':{**e.payload,'run_fingerprint':fingerprint(r),'metric_fingerprints':[fingerprint(m) for m in metrics]}}) if e.event_type=='EXPERIMENT_RUN_COMPLETED' else e for e in snap.events]
    snap=snap.model_copy(update={'runs':[r],'metrics':metrics,'events':events})
    summary=build_result_summary(snap)
    assert sum(c['failure_count'] for c in summary.conditions)==1 and summary.metrics[0]['denominator']==4
    assert summary.warnings and any('Failures' in w for w in summary.warnings)
    out=analysis_output(AnalysisService._context(snap,summary),{'analysis_id':'ANALYSIS_TEST','version':1})
    assert any(i['why_it_matters']=='ignored_failures' for i in scientific_findings(out.analysis,summary,selected_experiment(snap)))


def test_secondary_contradictory_signal_is_supplied_and_cherry_pick_flagged(completed):
    snap=snapshot(completed);summary=build_result_summary(snap)
    secondary=[{'metric_id':'METRIC_SECOND_'+name,'name':'cost_per_attempt','role':'secondary','condition':name,
        'value':value,'unit':'operation','denominator':4,'direction':'lower','raw_sha256':summary.raw_artifact['sha256']}
        for name,value in [('baseline',1.),('clipped',2.)]]
    summary=summary.model_copy(update={'metrics':[*summary.metrics,*secondary],
        'differences':[*summary.differences,{'name':'cost_per_attempt','direction':'lower','improvement':-1.,
            'control':'baseline','intervention':'clipped','control_value':1.,'intervention_value':2.,
            'metric_ids':[m['metric_id'] for m in secondary]}]})
    # This service test supplies a bounded deterministic offline preregistered
    # summary; it does not insert post-hoc metrics into the live/canonical ledger.
    spec=selected_experiment(snap).model_copy(update={'secondary_metrics':['cost_per_attempt']})
    context=AnalysisService._context(snap,summary);context['experiment_spec']=spec.model_dump(mode='json')
    a=analysis_output(context,{'analysis_id':'ANALYSIS_TEST','version':1}).analysis
    assert all(m['metric_id'] in a.metric_ids for m in secondary)
    assert all(any(m['condition'] in f and m['name'] in f for f in a.key_findings) for m in secondary)
    assert not any(i['why_it_matters']=='secondary_omitted' for i in scientific_findings(a,summary,spec))
    bad=a.model_copy(update={'key_findings':a.key_findings[:2],'claims':a.claims[:2]})
    assert any(i['why_it_matters']=='secondary_omitted' for i in scientific_findings(bad,summary,spec))

@pytest.mark.parametrize('direction,control,intervention,expected',[('lower',.8,.5,True),('higher',.5,.8,True),('higher',.8,.5,False)])
def test_structured_metric_direction_and_threshold(direction,control,intervention,expected,completed,monkeypatch):
    snap=snapshot(completed);spec=selected_experiment(snap).model_copy(update={'success_criteria':{
        'comparison':{'control':'baseline','intervention':'clipped','direction':direction,'minimum_improvement':.1}},
        'falsification_criteria':{'comparison':{'maximum_improvement':0}}})
    metrics=[m.model_copy(update={'metric_value':control if m.metadata['condition']=='baseline' else intervention}) for m in snap.metrics]
    snap=snap.model_copy(update={'experiments':[spec],'metrics':metrics})
    import autolab.analysis.result_summary as module
    monkeypatch.setattr(module,'evidence_pins',lambda snapshot,run:{'mock_arithmetic_only':True})
    from autolab.implementation import persistence as implementation_persistence
    original=snapshot(completed)
    checks=implementation_persistence.current_checks(original,original.implementations[-1])
    monkeypatch.setattr(implementation_persistence,'current_checks',lambda snapshot,implementation:checks)
    result=build_result_summary(snap)
    assert result.criteria['success_met']==expected
    assert result.differences[0]['direction']==direction
    assert result.criteria['falsification_met']==(not expected)


def test_unknown_direction_not_guessed(completed):
    spec=selected_experiment(snapshot(completed)).model_copy(update={'success_criteria':{'description':'Novel unknown metric criterion'}})
    assert comparison_contract(spec) is None


def test_zero_control_relative_difference_undefined(completed,monkeypatch):
    # Test persisted summary arithmetic directly by controlled snapshot seam.
    snap=snapshot(completed);metrics=[m.model_copy(update={'metric_value':0.}) for m in snap.metrics]
    snap=snap.model_copy(update={'metrics':metrics})
    import autolab.analysis.result_summary as summary_module
    # Explicit mocked trusted-admission seam only for zero arithmetic, not a
    # production valid-result bypass. Real eligibility tested separately.
    monkeypatch.setattr(summary_module,'evidence_pins',lambda snapshot,run:{'mock_arithmetic_only':True})
    summary=build_result_summary(snap)
    assert summary.differences[0]['relative_difference'] is None and summary.differences[0]['relative_difference_percent'] is None

@pytest.mark.parametrize('defect',['missing','duplicate','imaginary','unsubstantiated_rebuttal'])
def test_revision_response_validation(defect,completed):
    run(service(completed).analyze(PROJECT));snap=snapshot(completed);a=current_analysis(snap);summary=build_result_summary(snap)
    r=s.ReviewRecord(review_id='HREV_TEST',project_id=PROJECT,review_type='analysis',target_type='analyses',target_id=a.analysis_id,
        verdict='REVISE',reviewer_role='critic',issues=[{'problem':'test'}])
    response=CritiqueResponse(review_id=r.review_id,issue_index=0,disposition='ACCEPT',reason='Correct with supplied evidence',evidence_ids=[summary.run_id])
    values={'missing':[],'duplicate':[response,response],
        'imaginary':[response.model_copy(update={'evidence_ids':['RUN_FAKE']})],
        'unsubstantiated_rebuttal':[response.model_copy(update={'disposition':'REBUT','evidence_ids':[]})]}[defect]
    with pytest.raises(AnalysisError):validate_responses(values,r,summary)


def test_concurrent_evidence_change_rechecked_before_persistence(completed):
    class MutatingAnalyst(Analyst):
        async def interpret(self,*args,**kwargs):
            out=await super().interpret(*args,**kwargs)
            snap=snapshot(completed);h=snap.hypotheses[0]
            completed.add_hypothesis(h.model_copy(update={'version':2,'statement':'Changed hypothesis while interpreting'}))
            return out
    with pytest.raises(AnalysisError):run(service(completed,MutatingAnalyst()).analyze(PROJECT))
    assert not snapshot(completed).analyses


def test_critic_cannot_mutate_run_or_metrics(completed):
    before=snapshot(completed);run(service(completed).run(PROJECT));after=snapshot(completed)
    assert before.runs==after.runs and before.metrics==after.metrics and before.experiments==after.experiments


def test_source_project_stopped_remains_ineligible(completed):
    completed.add_decision(s.NextDecision(decision_id='DEC_STOP',project_id=PROJECT,action='STOP',reason='Terminal parent',remaining_budget_usd=100))
    with pytest.raises(AnalysisError,match='COMPLETED'):run(service(completed).analyze(PROJECT))


def test_analysis_agent_uses_real_transport_shape_offline(completed,monkeypatch):
    from autolab.analysis.agent import OmnigentAnalysisAgent
    snap=snapshot(completed);summary=build_result_summary(snap);context=AnalysisService._context(snap,summary)
    assignment={'analysis_id':'ANALYSIS_TEST','version':1};out=analysis_output(context,assignment)
    agent=OmnigentAnalysisAgent();calls=[]
    async def invoke(path,prompt,**kwargs):
        calls.append((path,json.loads(prompt),kwargs));return out.model_dump_json()
    monkeypatch.setattr(agent.transport,'invoke_agent',invoke)
    assert run(agent.interpret(context,assignment)).analysis==out.analysis
    assert calls[0][0].name=='analyst.yaml' and calls[0][2]['role']=='analyst'
    assert calls[0][1]['scientific_context']['result_summary']==summary.model_dump(mode='json')

@pytest.mark.parametrize('raw',['{}','not json','x'*31000])
def test_actual_analysis_transport_malformed_output_no_retry(completed,monkeypatch,raw):
    from autolab.analysis.agent import OmnigentAnalysisAgent
    agent=OmnigentAnalysisAgent();count=[]
    async def invoke(*a,**k):count.append(1);return raw
    monkeypatch.setattr(agent.transport,'invoke_agent',invoke)
    snap=snapshot(completed);context=AnalysisService._context(snap,build_result_summary(snap))
    with pytest.raises(AnalysisError):run(agent.interpret(context,{'analysis_id':'ANALYSIS_TEST','version':1}))
    assert count==[1]


def test_existing_critic_analysis_transport_is_independent_offline(completed,monkeypatch):
    from autolab.hypotheses.agent import OmnigentScientificCritic
    critic=OmnigentScientificCritic();snap=snapshot(completed);summary=build_result_summary(snap);context=AnalysisService._context(snap,summary)
    a=analysis_output(context,{'analysis_id':'ANALYSIS_TEST','version':1}).analysis
    assignment={'review_id':'HREV_TEST','project_id':PROJECT,'target_id':a.analysis_id,'target_version':1}
    batch=ReviewBatch(reviews=[s.ReviewRecord(**assignment,review_type='analysis',target_type='analyses',reviewer_role='critic',verdict='PASS')]);calls=[]
    async def invoke(path,prompt,**kwargs):calls.append((path,json.loads(prompt),kwargs));return batch.model_dump_json()
    monkeypatch.setattr(critic.transport,'invoke_agent',invoke)
    assert run(critic.review_analysis(context,a,assignment)).reviews[0].verdict=='PASS'
    assert calls[0][0].name=='critic.yaml' and calls[0][1]['review_mode']=='analysis' and calls[0][2]['role']=='critic'


def test_ledger_v2_migration_preserves_original_analysis_and_reviews(tmp_path):
    # Model a real pre-Phase11 schema with verbatim legacy JSON and review target.
    from autolab.ledger.database import LedgerDatabase
    from autolab.ledger_smoke import populate_demo
    path=tmp_path/'v2.db'
    with ResearchLedger(path) as l:
        demo=populate_demo(l);project=demo[0];spec=demo[6]
        impl=s.ImplementationRecord(implementation_id='IMPL_LEGACY',project_id=project.project_id,
            experiment_id=spec.experiment_id,code_path='legacy.py',code_version='legacy')
        l.add_implementation(impl)
        r=s.ExperimentRun(run_id='RUN_LEGACY',project_id=project.project_id,experiment_id=spec.experiment_id,implementation_id=impl.implementation_id)
        l.add_run(r)
        a=s.ScientificAnalysis(analysis_id='ANALYSIS_LEGACY',project_id=project.project_id,experiment_id=spec.experiment_id,run_id=r.run_id,
            hypothesis_assessment='INCONCLUSIVE',interpretation='Legacy synthetic state')
        l.add_analysis(a)
        review=s.ReviewRecord(review_id='HREV_LEGACY',project_id=project.project_id,review_type='analysis',target_type='analyses',target_id=a.analysis_id,verdict='REVISE',reviewer_role='critic')
        l.add_review(review)
    c=sqlite3.connect(path);c.execute('PRAGMA foreign_keys=OFF')
    for suffix in ('no_replace','no_update','no_delete'):c.execute('DROP TRIGGER analyses_'+suffix)
    c.execute('ALTER TABLE analyses RENAME TO temporary_analyses')
    c.execute('CREATE TABLE analyses (created_at TEXT NOT NULL,record_json TEXT NOT NULL,analysis_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,experiment_id TEXT NOT NULL,experiment_version INTEGER NOT NULL,run_id TEXT NOT NULL)')
    legacy=a.model_dump(mode='json')
    for k in ('version','hypothesis_id','hypothesis_version','metric_ids','evidence_pins','criteria_evaluation','confounders','claims','causal_scope','generalization_scope'):legacy.pop(k)
    original=json.dumps(legacy)
    c.execute('INSERT INTO analyses VALUES (?,?,?,?,?,?,?)',(a.created_at.isoformat(),original,a.analysis_id,a.project_id,a.experiment_id,1,a.run_id))
    c.execute('DROP TABLE temporary_analyses');c.execute('PRAGMA user_version=2');c.commit();c.close()
    with ResearchLedger(path) as l:
        assert l.database.connection.execute('PRAGMA user_version').fetchone()[0]==3
        assert l.database.connection.execute('SELECT record_json FROM analyses').fetchone()[0]==original
        first=l.get(s.ScientificAnalysis,a.analysis_id,version=1);assert first.version==1 and not first.evidence_pins
        second=l.add_analysis(first.model_copy(update={'version':2,'interpretation':'Revised interpretation'}))
        assert l.get(s.ScientificAnalysis,a.analysis_id)==second
        assert l.get(s.ReviewRecord,review.review_id)==review
        assert not l.database.connection.execute('PRAGMA foreign_key_check').fetchall()
        with pytest.raises(sqlite3.IntegrityError):l.database.connection.execute('UPDATE analyses SET run_id=?',('RUN_WRONG',))


def test_analysis_model_output_schema_has_matching_bounds():
    from autolab.analysis.agent import analysis_output_schema
    fields=analysis_output_schema()['$defs']['ScientificAnalysis']['properties']
    for name in ('claims','confounders','key_findings','limitations','remaining_uncertainties','unexpected_findings'):
        assert fields[name]['maxItems']==8
    assert fields['confidence']['const']==0 and fields['recommended_followup']['maxItems']==0


def test_real_saved_experiment_still_blocked_no_analysis():
    from autolab.runtime_smoke_helpers import verify_real_run_blocked
    check=verify_real_run_blocked()
    if not check['available']:pytest.skip('Ignored saved actual project unavailable')
    assert check['rejected'] and check['snapshot_sha256']=='cee272e362ed83c97b13839112c80d50cd8b83996dc28c85ee62377ff119598e'

@pytest.mark.parametrize('raw',['{}','not json','x'*31000])
def test_actual_critic_transport_malformed_output_no_retry(completed,monkeypatch,raw):
    from autolab.hypotheses.agent import OmnigentScientificCritic
    critic=OmnigentScientificCritic();count=[]
    async def invoke(*a,**k):count.append(1);return raw
    monkeypatch.setattr(critic.transport,'invoke_agent',invoke)
    snap=snapshot(completed);context=AnalysisService._context(snap,build_result_summary(snap))
    a=analysis_output(context,{'analysis_id':'ANALYSIS_TEST','version':1}).analysis
    with pytest.raises(AnalysisError):run(critic.review_analysis(context,a,{'review_id':'HREV_TEST'}))
    assert count==[1]


def test_fresh_implementation_validation_distinguished_from_planning_notes(completed):
    snap=snapshot(completed);summary=build_result_summary(snap);context=AnalysisService._context(snap,summary)
    receipt=summary.implementation_validation
    assert receipt['static_pass'] and receipt['tests_pass'] and receipt['framework_checks']>0 and receipt['generated_tests']>0
    assert receipt['audit_verdict']=='PASS' and receipt['implementation_id'] in summary.available_evidence_ids
    assert receipt['audit_id'] in summary.available_evidence_ids
    assert 'implementation_declared_planning_notes' in context and context['run_metadata']['status']=='COMPLETED'
    assert {o['condition'] for o in summary.representative_observations}=={'baseline','clipped'}


def test_analyst_unknown_direction_inconclusive_is_valid(completed):
    snap=snapshot(completed);summary=build_result_summary(snap)
    criteria={**summary.criteria,'success_met':None,'falsification_met':None,'comparison':None}
    summary=summary.model_copy(update={'criteria':criteria,'differences':[],
        'warnings':['Metric direction unresolved; no threshold invented']})
    a=analysis_output(AnalysisService._context(snap,summary),{'analysis_id':'ANALYSIS_TEST','version':1},assessment='INCONCLUSIVE').analysis
    assert not scientific_findings(a,summary,selected_experiment(snap))


def test_changed_hypothesis_blocks_analyze_route_before_any_model(completed):
    snap=snapshot(completed);h=snap.hypotheses[0]
    completed.add_hypothesis(h.model_copy(update={'version':2}))
    agent=Analyst();workflow=service(completed,agent)
    with pytest.raises(AnalysisError):run(workflow.analyze(PROJECT))
    assert agent.calls==0 and not snapshot(completed).analyses


def test_wrong_review_version_cannot_authorize_current_analysis(completed):
    result=run(service(completed,critic=Critic(['REVISE','PASS'])).run(PROJECT));snap=snapshot(completed)
    assert result.version==2 and reviewed_analysis(snap)
    reviews=[r for r in snap.reviews if not (r.review_type=='analysis' and r.target_version==2)]
    stale=snap.model_copy(update={'reviews':reviews})
    assert not reviewed_analysis(stale) and derive_control_state(stale)=='ANALYSIS_REVIEW'


@pytest.mark.parametrize('direction', ['lower','higher'])
def test_explicit_strict_zero_operator_preserves_existing_criteria(direction,completed,monkeypatch):
    snap=snapshot(completed)
    spec=selected_experiment(snap).model_copy(update={
        'success_criteria':{'comparison':{'control':'baseline','intervention':'clipped',
            'direction':direction,'minimum_improvement':0,'threshold_operator':'>'}},
        'falsification_criteria':{'comparison':{'control':'baseline','intervention':'clipped',
            'direction':direction,'maximum_improvement':0,'threshold_operator':'<='}}})
    import autolab.analysis.result_summary as module
    monkeypatch.setattr(module,'selected_experiment',lambda snapshot:spec)
    monkeypatch.setattr(module,'evidence_pins',lambda snapshot,run:{'mock_arithmetic_only':True})
    summary=build_result_summary(snap)
    assert summary.criteria['success_met'] is (direction=='lower')
    assert summary.criteria['falsification_met'] is (direction=='higher')
    assert 'threshold_operator' in summary.criteria['success_preregistered']['comparison']


@pytest.mark.parametrize('operator',['>=','invented'])
def test_incompatible_explicit_zero_operator_is_not_guessed(operator,completed):
    spec=selected_experiment(snapshot(completed)).model_copy(update={'success_criteria':{
        'comparison':{'control':'baseline','intervention':'clipped','direction':'lower',
            'minimum_improvement':0,'threshold_operator':operator}}})
    with pytest.raises(AnalysisError,match='threshold operator'):
        comparison_contract(spec)


def test_harm_hypothesis_support_is_separate_from_metric_quality(completed):
    snap=snapshot(completed);summary=build_result_summary(snap)
    difference={**summary.differences[0], 'control_value':.075,'intervention_value':.175,
        'direction':'higher','metric_direction':'lower','improvement':.1}
    summary=summary.model_copy(update={'differences':[difference],
        'criteria':{**summary.criteria,'success_met':True,'falsification_met':False}})
    context={'result_summary':summary.model_dump(mode='json'),'experiment_spec':selected_experiment(snap).model_dump(mode='json')}
    output=analysis_output(context,{'analysis_id':'ANALYSIS_TEST','version':1})
    accurate=output.analysis.model_copy(update={'interpretation':'baseline has lower error; clipping increased error within this fixed fixture.'})
    assert not any(i['why_it_matters']=='wrong_direction' for i in scientific_findings(accurate,summary,selected_experiment(snap)))
    false=accurate.model_copy(update={'interpretation':'clipped is better than baseline.'})
    assert any(i['why_it_matters']=='wrong_direction' for i in scientific_findings(false,summary,selected_experiment(snap)))
