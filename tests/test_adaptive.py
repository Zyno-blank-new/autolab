"""Offline Phase 12: deterministic scientific state, no paid/network requests."""
import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import pytest
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.orchestration.orchestrator import Orchestrator,IllegalDecisionError
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.state_machine import selected_experiment,current_implementation,selected_hypothesis,derive_control_state,approval_for
from autolab.orchestration.budget import calculate_budget
from autolab.orchestration.adaptive import research_history,telemetry,state_pin,source_links,duplicate_of,round_count,work_block
from autolab.preparation.manifest import fingerprint,current_plan,current_manifest
from autolab.feasibility.persistence import spec_fingerprint
from autolab.experiment_design.context import build_context
from autolab.experiment_design.service import ExperimentDesignPipeline
from autolab.experiment_design.validation import spec_from_candidate
from autolab.feasibility.service import FeasibilityService
from autolab.feasibility.approval import ApprovalService
from autolab.feasibility.models import FeasibilityInputs,ResourceAccess,CostInput,EstimateRange
from autolab.preparation.service import PreparationService
from autolab.preparation.models import ResourcePreparationPlan
from autolab.readiness.service import ReadinessService
from autolab.implementation.service import ImplementationService
from autolab.implementation.models import TestContract as FrameworkTestContract
from autolab.runtime.service import ExperimentRuntime
from autolab.runtime.adapters import ScalarFixtureAdapter
from autolab.runtime_smoke_helpers import authorize_execution,PROJECT
from test_runtime import ready_runtime
from test_analysis import Analyst,Critic,service
from phase9_helpers import Implementer,Auditor
from phase12_helpers import Planner,Designer,DesignCritic

run=asyncio.run
snap=lambda l:load_snapshot(l,PROJECT)

@pytest.fixture
def reviewed(ready_runtime):
    runtime,_,spec=ready_runtime
    run(runtime.run(PROJECT));run(service(runtime.ledger).run(PROJECT))
    ledger=runtime.ledger
    h=selected_hypothesis(snap(ledger))
    ledger.add_review(s.ReviewRecord(review_id=ledger.next_id('HREV'),project_id=PROJECT,target_type='hypotheses',
        target_id=h.hypothesis_id,target_version=h.version,review_type='hypothesis',reviewer_role='critic',verdict='PASS'))
    scope=ledger.create_project(s.ResearchCharter(project_id='PROJECT_ADAPTIVE_TEST_SCOPE',title='Explicit offline scope',
        research_question='Does activation mediate clipping gain?',objective='Distinguish activation mechanism with bounded follow-up',
        primary_outcome='Paired error',budget_usd=100,max_runtime_minutes=240,
        constraints={'parent_project':PROJECT,'max_rounds':2,'max_experiments':2}))
    ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'),project_id=PROJECT,event_type='LINKED_RESEARCH_SCOPE_AUTHORIZED',
        actor='test-human',summary='Explicit synthetic test fixture scope',payload={'linked_project_id':scope.project_id,
        'parent_charter_fingerprint':fingerprint(snap(ledger).charter),'linked_charter_fingerprint':fingerprint(scope)}))
    return ledger


def d(snapshot,action='RUN_FOLLOWUP',target='experiment_designer',ids=()):
    return s.NextDecision(decision_id='DEC_CHECK',project_id=PROJECT,action=action,target_agent=target,
        required_context_ids=list(ids),reason='Resolve current reviewed uncertainty',remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd)

@pytest.mark.parametrize('field',['metrics','differences','conditions','criteria','limitations','critic','unresolved_confounders'])
def test_post_result_context(reviewed,field):
    ctx=ContextBuilder().build(snap(reviewed))
    assert ctx.current_records['reviewed_result'][field]
    assert ctx.current_records['analysis']['reviewed_current']
    assert ctx.summaries['research_history'][0]['run_id']=='RUN_0001'
    assert ctx.budget.remaining_budget_usd==100 and ctx.time.remaining_minutes>0

@pytest.mark.parametrize('action,target',[('GATHER_EVIDENCE','evidence'),('REFINE_HYPOTHESIS','hypothesis'),
    ('RUN_FOLLOWUP','experiment_designer'),('DESIGN_EXPERIMENT','experiment_designer'),
    ('ACCEPT_HYPOTHESIS','planner'),('REJECT_HYPOTHESIS','planner'),('STOP',None)])
def test_legal_adaptive_actions(reviewed,action,target):
    assert DecisionValidator().validate(d(snap(reviewed),action,target),snap(reviewed)).valid

@pytest.mark.parametrize('target',['nonexistent','implementer','preparation','experiment_runner'])
def test_invalid_followup_target(reviewed,target):
    assert not DecisionValidator().validate(d(snap(reviewed),target=target),snap(reviewed)).valid


def test_receipt_lineage_and_restart(reviewed):
    route=run(Orchestrator(reviewed,Planner(['RUN_FOLLOWUP'])).decide(PROJECT,max_repairs=0))
    snapshot=snap(reviewed)
    receipt=next(e for e in snapshot.events if e.event_type=='ADAPTIVE_DECISION_CREATED')
    assert receipt.payload['parent_analysis_id']=='ANALYSIS_0001' and receipt.payload['parent_run_id']=='RUN_0001'
    assert receipt.payload['dispatch_pin']==state_pin(snapshot) and round_count(snapshot)==1
    with ResearchLedger(reviewed.database.path) as reopened:
        assert research_history(snap(reopened))==research_history(snapshot)
        assert snap(reopened).authorized_scope==snapshot.authorized_scope

@pytest.mark.parametrize('change',['analysis','hypothesis','evidence','charter','cost','metric'])
def test_old_adaptive_decision_stale(reviewed,change):
    orch=Orchestrator(reviewed,Planner(['RUN_FOLLOWUP']))
    route=run(orch.decide(PROJECT,max_repairs=0));before=snap(reviewed)
    if change=='hypothesis':reviewed.add_hypothesis(before.hypotheses[-1].model_copy(update={'version':2}))
    elif change=='analysis':reviewed.add_analysis(before.analyses[-1].model_copy(update={'version':2}))
    elif change=='cost':reviewed.add_cost(s.CostRecord(cost_id=reviewed.next_id('COST'),project_id=PROJECT,category='Known bill',actual_usd=1))
    elif change=='metric':
        # Snapshot seam models a scientific change; immutable ledger rejects writes to originals.
        changed=before.model_copy(update={'metrics':[m.model_copy(update={'metric_value':9}) for m in before.metrics]})
        assert not DecisionValidator().validate(reviewed.get(s.NextDecision,route.decision_id),changed).valid;return
    elif change=='evidence':
        source=reviewed.add_source(s.SourceRecord(source_id=reviewed.next_id('SRC'),project_id=PROJECT,title='New synthetic contradiction'))
        reviewed.add_evidence(s.EvidenceRecord(evidence_id=reviewed.next_id('EVID'),project_id=PROJECT,source_id=source.source_id,
            claim='Contradiction fixture',tags=['CONTRADICTING']))
    elif change=='charter':
        scope=before.authorized_scope.model_copy(update={'project_id':'PROJECT_NEW_SCOPE','budget_usd':50})
        reviewed.create_project(scope)
        reviewed.add_event(s.EventRecord(event_id=reviewed.next_id('EVENT'),project_id=PROJECT,event_type='LINKED_RESEARCH_SCOPE_AUTHORIZED',
            actor='human',summary='Explicit changed scope',payload={'linked_project_id':scope.project_id,
                'parent_charter_fingerprint':fingerprint(before.charter),'linked_charter_fingerprint':fingerprint(scope)}))
    with pytest.raises(IllegalDecisionError):run(orch.execute_adaptive(route))
    assert before.runs==snap(reviewed).runs

@pytest.mark.parametrize('action',['ACCEPT_HYPOTHESIS','REJECT_HYPOTHESIS','STOP'])
def test_disposition_preserves_evidence_and_reason(reviewed,action):
    before=snap(reviewed);orch=Orchestrator(reviewed,Planner([action]))
    route=run(orch.decide(PROJECT,max_repairs=0));run(orch.execute_adaptive(route));after=snap(reviewed)
    for field in ('charter','hypotheses','experiments','runs','metrics','analyses','reviews'):
        assert getattr(before,field)==getattr(after,field)
    kind={'STOP':'RESEARCH_STOPPED','ACCEPT_HYPOTHESIS':'HYPOTHESIS_ACCEPTED_FOR_CHARTER','REJECT_HYPOTHESIS':'HYPOTHESIS_REJECTED'}[action]
    assert next(e for e in after.events if e.event_type==kind).payload['reason']
    if action=='STOP':assert derive_control_state(after)=='COMPLETED'


def test_stale_result_excluded_current_but_history_retained(reviewed):
    before=snap(reviewed)
    reviewed.add_hypothesis(before.hypotheses[-1].model_copy(update={'version':2}))
    ctx=ContextBuilder().build(snap(reviewed))
    assert not ctx.current_records['reviewed_result'] and not ctx.current_records['analysis']['fresh']
    assert ctx.summaries['research_history'][0]['analysis']['assessment']=='SUPPORTED'

@pytest.mark.parametrize('case',['budget','time','rounds','pause','human_stop','experiments'])
def test_hard_bounds(reviewed,case):
    before=snap(reviewed)
    if case=='budget':reviewed.add_cost(s.CostRecord(cost_id=reviewed.next_id('COST'),project_id=PROJECT,category='Known spent',actual_usd=100))
    if case=='time':before=before.model_copy(update={'authorized_scope':before.authorized_scope.model_copy(update={'created_at':s.utc_now()-timedelta(hours=5)})})
    if case in ('rounds','experiments'):
        scope=before.authorized_scope.model_copy(update={'constraints':{**before.authorized_scope.constraints,
            'max_rounds':1} if case=='rounds' else {**before.authorized_scope.constraints,'max_experiments':1}})
        before=before.model_copy(update={'authorized_scope':scope})
    if case=='pause':reviewed.add_event(s.EventRecord(event_id=reviewed.next_id('EVENT'),project_id=PROJECT,event_type='PROJECT_PAUSED',actor='human',summary='Pause'))
    if case=='human_stop':reviewed.add_decision(d(before,'STOP',None))
    snapshot=before if case in ('time','rounds','experiments') else snap(reviewed)
    assert not DecisionValidator().validate(d(snapshot),snapshot).valid
    assert DecisionValidator().validate(d(snapshot,'STOP',None),snapshot).valid


def test_duplicate_requires_explicit_replication(reviewed):
    snapshot=snap(reviewed);spec=selected_experiment(snapshot)
    assert duplicate_of(snapshot,spec)=='EXP_PHASE10'
    copy=spec.model_copy(update={'title':'New misleading label','objective':'New purported mechanism'})
    assert duplicate_of(snapshot,copy)=='EXP_PHASE10'
    from autolab.orchestration.adaptive import replication_reason
    repeat=copy.model_copy(update={'dataset_requirements':{**copy.dataset_requirements,'purpose':'replication','replication_reason':'Independent repeat assesses reproducibility'}})
    assert replication_reason(repeat)


def design_and_select(ledger):
    before=snap(ledger);planner=Planner(['RUN_FOLLOWUP','SELECT_EXPERIMENT']);orch=Orchestrator(ledger,planner)
    route=run(orch.decide(PROJECT,max_repairs=0));designer=Designer(selected_experiment(before))
    pipeline=ExperimentDesignPipeline(ledger,designer,DesignCritic())
    run(orch.execute_adaptive(route,services={'design':pipeline}))
    assert designer.contexts[0].reviewed_result['parent_run_id']=='RUN_0001'
    route2=run(orch.decide(PROJECT,max_repairs=0))
    return orch,selected_experiment(snap(ledger)),before,route2


def test_followup_selection_lineage_and_fresh_approval(reviewed):
    orch,spec,before,route=design_and_select(reviewed)
    after=snap(reviewed)
    assert spec.experiment_id!='EXP_PHASE10' and derive_control_state(after)=='AWAITING_HUMAN_APPROVAL'
    assert not approval_for(after,s.PlannerAction.PREPARE_RESOURCES)
    selected=next(e for e in reversed(after.events) if e.event_type=='EXPERIMENT_SELECTED')
    for key,value in [('parent_experiment_id','EXP_PHASE10'),('parent_run_id','RUN_0001'),('parent_analysis_id','ANALYSIS_0001')]:
        assert selected.payload[key]==value
    assert selected.payload['followup_reason'] and selected.payload['round_id']=='ROUND_0002'
    assert after.experiments[0]==before.experiments[0] and after.runs==before.runs and len(after.candidates)==2
    assert round_count(after)==2
    assert run(orch.continue_research(PROJECT,max_steps=2))['status']=='AWAITING_HUMAN_APPROVAL'


def prepare_followup(ledger,root,spec,*,approve=True,estimate=0):
    from autolab.feasibility.capability_registry import CapabilityRegistry
    registry=CapabilityRegistry.local(root)
    inputs=FeasibilityInputs(resource_access=[ResourceAccess(requirement=x,status='AVAILABLE') for x in spec.required_resources],
        costs=[CostInput(category='Local fixture',unit_price_usd=estimate,units=EstimateRange(minimum=1,maximum=1))],
        runtime_minutes=EstimateRange(minimum=1,maximum=60),compute_requirements=['Local CPU'],storage_gb=EstimateRange(maximum=.001))
    FeasibilityService(ledger,registry).assess(PROJECT,spec.experiment_id,inputs)
    approval=ApprovalService(ledger,allow_test_human=True);packet=approval.request_approval(PROJECT,spec.experiment_id)
    approval.record_human_decision(PROJECT,spec.experiment_id,spec.version,'APPROVE' if approve else 'REJECT',packet_id=packet.packet_id,
        actor='test-human',max_cost_usd=10,max_runtime_minutes=60,acknowledge_unknowns=True,
        approved_actions=['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT'])
    return registry


def test_rejected_followup_cannot_execute(reviewed,tmp_path):
    _,spec,_,_=design_and_select(reviewed)
    prepare_followup(reviewed,tmp_path,spec,approve=False)
    assert not DecisionValidator().validate(d(snap(reviewed),'PREPARE_RESOURCES','preparation'),snap(reviewed)).valid


def test_cross_round_budget_does_not_reset(reviewed,tmp_path):
    _,spec,_,_=design_and_select(reviewed)
    reviewed.add_cost(s.CostRecord(cost_id=reviewed.next_id('COST'),project_id=PROJECT,category='Prior actual',actual_usd=95))
    with pytest.raises(ValueError):prepare_followup(reviewed,tmp_path,spec,estimate=8)
    assert calculate_budget(snap(reviewed)).remaining_budget_usd==5


def test_full_two_round_vertical_slice_reuses_every_downstream_service(reviewed,tmp_path):
    _,spec,before,_=design_and_select(reviewed)
    registry=prepare_followup(reviewed,tmp_path,spec)
    old_plan=current_plan(before);old_record=current_implementation(before)
    rows=[{'sample_id':'new-'+str(i),'prediction':p,'target':t} for i,(p,t) in enumerate([(.1,.2),(.3,.4),(.7,.9),(.9,.7)])]
    requirement=old_plan.resource_requirements[0].model_copy(update={'parameters':{'data':rows,'seed':19,'specification':'Preregistered independent in-range mechanism negative control'}})
    class Preparer:
        async def plan(self,context,assignment,**kwargs):return ResourcePreparationPlan(**assignment,resource_requirements=[requirement])
    class ReadinessAuditor:
        async def audit(self,context,assignment):return s.ReadinessReport(**assignment,resource_readiness=True,technical_readiness=True,
            scientific_readiness=True,quality_readiness=True,verdict='PASS',metadata={'semantic_findings':[{'gate':'scientific',
            'resource_ids':[p['resource_id'] for p in context['resource_pins']],'finding':'Preregistered synthetic in-range cohort matches independent scalar protocol','evidence':'Exact frozen cohort contract'}]})
    planner=Planner(['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT','RUN_EXPERIMENT','ANALYZE_RESULT','STOP'])
    orch=Orchestrator(reviewed,planner)
    preparer=PreparationService(reviewed,Preparer(),registry=registry,root=tmp_path)
    auditor=ReadinessService(reviewed,ReadinessAuditor())
    route=run(orch.decide(PROJECT,max_repairs=0));run(orch.execute_adaptive(route,services={'preparation':preparer,'readiness':auditor}))
    manifest=current_manifest(snap(reviewed));pin=manifest.resources[0]
    old_contract=FrameworkTestContract.model_validate(old_record.metadata['test_contract'])
    contract=old_contract.model_copy(update={'spec_fingerprint':spec_fingerprint(spec),
        'setup_context':{'experiment_id':spec.experiment_id,'experiment_version':1,'seed':19,'resource_hashes':{pin.resource_id:pin.checksum}},
        'fixture_resources':{pin.resource_id:rows}})
    implementer=Implementer(mutate_source=lambda files:{name:value.replace('EXP_PHASE9',spec.experiment_id) for name,value in files.items()})
    implementation=ImplementationService(reviewed,implementer,Auditor(),root=tmp_path,contracts={spec_fingerprint(spec):contract})
    route=run(orch.decide(PROJECT,max_repairs=0));result=run(orch.execute_adaptive(route,services={'implementation':implementation}))
    assert result.status=='READY'
    # Explicit isolated test-human expands only this exact implementation's scope.
    authorize_execution(reviewed,current_implementation(snap(reviewed)))
    runtime=ExperimentRuntime(reviewed,root=tmp_path,adapters={spec_fingerprint(spec):ScalarFixtureAdapter(spec_fingerprint(spec))})
    route=run(orch.decide(PROJECT,max_repairs=0));r=run(orch.execute_adaptive(route,services={'runtime':runtime}))
    assert r.status=='COMPLETED' and r.run_id!='RUN_0001'
    route=run(orch.decide(PROJECT,max_repairs=0));result=run(orch.execute_adaptive(route,services={'analysis':service(reviewed)}))
    assert result.verdict=='PASS'
    route=run(orch.decide(PROJECT,max_repairs=0));assert route.action=='STOP'
    final=snap(reviewed)
    assert len(final.runs)==2 and len(final.analyses)==2 and final.analyses[-1].hypothesis_assessment=='NOT_SUPPORTED'
    assert final.runs[0]==before.runs[0] and final.analyses[0]==before.analyses[0]
    assert round_count(final)==2 and len(research_history(final))==2
    assert [x['analysis']['assessment'] for x in research_history(final)]==['SUPPORTED','NOT_SUPPORTED']
    assert planner.contexts[-1].current_records['reviewed_result']['parent_run_id']==r.run_id
    assert telemetry(final)['counts']['experiments_executed']==2
    # Third-round work remains forbidden even without terminal STOP overlay.
    checkpoint=final.model_copy(update={'decisions':[x for x in final.decisions if x.action!='STOP']})
    assert work_block(checkpoint,s.PlannerAction.RUN_FOLLOWUP)
    assert not DecisionValidator().validate(d(checkpoint),checkpoint).valid
    import os,json
    artifact=os.environ.get('AUTOLAB_PHASE12_ARTIFACT')
    if artifact:
        from autolab.orchestration.adaptive import round_history
        Path(artifact).write_text(json.dumps({'validation':'DETERMINISTIC_OFFLINE_FULL_PATH','snapshot':final.model_dump(mode='json'),
            'research_history':research_history(final),'round_history':round_history(final),'telemetry':telemetry(final),
            'planner_calls':planner.calls,'round1_records_preserved':True,'fresh_test_human_approval':True,
            'third_round_blocked':True,'paid_model_calls':0,'new_actual_runs':2},indent=2)+'\n')

@pytest.mark.parametrize('max_steps',[0,21,True,-1])
def test_continue_bound_argument(reviewed,max_steps):
    with pytest.raises(ValueError):run(Orchestrator(reviewed,Planner([])).continue_research(PROJECT,max_steps=max_steps))


def test_continue_only_calls_pi_at_scientific_boundaries(reviewed):
    planner=Planner(['RUN_FOLLOWUP','SELECT_EXPERIMENT']);orch=Orchestrator(reviewed,planner)
    result=run(orch.continue_research(PROJECT,max_steps=4,services={'design':ExperimentDesignPipeline(reviewed,Designer(selected_experiment(snap(reviewed))),DesignCritic())}))
    assert result['status']=='AWAITING_HUMAN_APPROVAL' and planner.calls==2


def test_specialist_failure_partial_round_visible_and_no_retry(reviewed):
    class Failure:
        ledger=reviewed
        async def generate(self,project):raise RuntimeError('Offline failure')
    orch=Orchestrator(reviewed,Planner(['RUN_FOLLOWUP']))
    route=run(orch.decide(PROJECT,max_repairs=0))
    with pytest.raises(RuntimeError):run(orch.execute_adaptive(route,services={'design':Failure()}))
    before=snap(reviewed)
    assert any(e.event_type=='ADAPTIVE_SPECIALIST_FAILED' for e in before.events)
    assert run(orch.continue_research(PROJECT))['status']=='RECONCILIATION_REQUIRED'
    with pytest.raises(IllegalDecisionError):run(orch.execute_adaptive(route))
    assert snap(reviewed).runs==before.runs


def test_malformed_planner_has_one_call_no_generic_stop(reviewed):
    class Malformed:
        calls=0
        async def propose(self,*args,**kwargs):self.calls+=1;return '{bad'
    planner=Malformed();before=snap(reviewed)
    with pytest.raises(RuntimeError):run(Orchestrator(reviewed,planner).continue_research(PROJECT))
    assert planner.calls==1 and snap(reviewed).decisions==before.decisions


def test_result_driven_evidence_reuses_existing_agent_pipeline(reviewed):
    from test_literature import FakeEvidence,FakeProvider,FIXTURES
    from autolab.literature.providers.arxiv import parse_feed
    from autolab.literature.service import EvidencePipeline
    from autolab.literature.retrieval import LiteratureService
    from autolab.literature.models import LiteratureLimits
    class AdaptiveEvidence(FakeEvidence):
        context=None
        async def generate_adaptive_queries(self,charter,count,context):
            self.context=context
            return await self.generate_queries(charter,count)
    papers,_=parse_feed((FIXTURES/'arxiv.xml').read_bytes(),15)
    agent=AdaptiveEvidence();limits=LiteratureLimits(query_count=2,top_k=2)
    pipeline=EvidencePipeline(reviewed,agent,LiteratureService([FakeProvider('arxiv',papers)],limits),limits)
    orch=Orchestrator(reviewed,Planner(['GATHER_EVIDENCE']))
    route=run(orch.decide(PROJECT,max_repairs=0));before=snap(reviewed)
    result=run(orch.execute_adaptive(route,services={'evidence':pipeline}))
    assert result.evidence_ids and agent.context['parent_analysis_id']=='ANALYSIS_0001'
    assert agent.context['limitations'] and agent.context['planner_request']['reason']
    assert snap(reviewed).runs==before.runs and snap(reviewed).analyses==before.analyses
    assert any(e.event_type=='ADAPTIVE_CONTROL_RETURNED' for e in snap(reviewed).events)


def test_refinement_reuses_hypothesis_and_independent_critic(reviewed):
    from autolab.hypotheses.service import HypothesisPipeline
    from autolab.hypotheses.models import RevisionBatch,ReviewBatch
    class Refiner:
        context=None
        async def refine(self,context,hypothesis,assignments):
            self.context=context
            h=hypothesis.model_copy(update={**assignments[0],'status':s.HypothesisStatus.REFINED,
                'rationale':'AGENT-GENERATED HYPOTHESIS. SUPPORTED BY EVIDENCE: None; LOW-CONFIDENCE. SCIENTIFIC INFERENCE / PROPOSED EXPLANATION: Clipping activation may mediate observed fixture difference.',
                'falsifiable_prediction':'The condition difference vanishes on independently frozen in-range inputs.',
                'novelty_score':.1,'testability_score':.9,'scientific_value_score':.5})
            return RevisionBatch(hypotheses=[h],responses=[])
    class HypothesisCritic:
        async def review(self,context,hypotheses,assignments,**kwargs):
            return ReviewBatch(reviews=[s.ReviewRecord(**a,target_type='hypotheses',review_type='hypothesis',
                reviewer_role='critic',verdict='PASS') for a in assignments])
    agent=Refiner();pipeline=HypothesisPipeline(reviewed,agent,HypothesisCritic())
    orch=Orchestrator(reviewed,Planner(['REFINE_HYPOTHESIS']))
    before=snap(reviewed);route=run(orch.decide(PROJECT,max_repairs=0))
    result=run(orch.execute_adaptive(route,services={'hypothesis':pipeline}))
    after=snap(reviewed)
    assert result.passed_hypothesis_ids and after.hypotheses[-1].version==2
    assert after.hypotheses[0]==before.hypotheses[0] and after.runs==before.runs and after.analyses==before.analyses
    assert agent.context.reviewed_result['assessment']=='SUPPORTED'
    assert selected_hypothesis(after).version==2


def test_linked_charter_cannot_be_silently_forged(reviewed):
    before=snap(reviewed)
    reviewed.add_event(s.EventRecord(event_id=reviewed.next_id('EVENT'),project_id=PROJECT,event_type='LINKED_RESEARCH_SCOPE_AUTHORIZED',
        actor='planner',summary='Forbidden forged scope',payload={'linked_project_id':before.authorized_scope.project_id}))
    with pytest.raises(ValueError):snap(reviewed)


def test_authorized_linked_charter_is_valid_supplied_context_id(reviewed):
    snapshot=snap(reviewed)
    assert DecisionValidator().validate(d(snapshot,'GATHER_EVIDENCE','evidence',[snapshot.authorized_scope.project_id]),snapshot).valid


def test_rejected_branch_cannot_be_designed_again_without_revision(reviewed):
    orch=Orchestrator(reviewed,Planner(['REJECT_HYPOTHESIS']))
    route=run(orch.decide(PROJECT,max_repairs=0));run(orch.execute_adaptive(route))
    snapshot=snap(reviewed)
    assert not DecisionValidator().validate(d(snapshot),snapshot).valid
    assert ContextBuilder().build(snapshot).current_records['hypothesis']['charter_disposition']=='HYPOTHESIS_REJECTED'


def test_local_evidence_inspection_is_agent_selected_no_literature_or_rerun(reviewed):
    from autolab.literature.models import QueryPlan
    from autolab.literature.service import EvidencePipeline
    class Agent:
        calls=0
        async def generate_adaptive_queries(self,charter,count,context):
            self.calls+=1
            assert context['parent_run_id']=='RUN_0001'
            return QueryPlan(inspect_existing_result=True,queries=[])
    class Retrieval:
        async def retrieve(self,queries):raise AssertionError('No paper retrieval for existing-artifact inspection')
    agent=Agent();pipeline=EvidencePipeline(reviewed,agent,Retrieval())
    orch=Orchestrator(reviewed,Planner(['GATHER_EVIDENCE','STOP']))
    before=snap(reviewed);route=run(orch.decide(PROJECT,max_repairs=0))
    result=run(orch.execute_adaptive(route,services={'evidence':pipeline}))
    after=snap(reviewed)
    assert not result.source_ids and not result.evidence_ids and not result.queries and agent.calls==1
    inspection=next(e for e in after.events if e.event_type=='LOCAL_RESULT_EVIDENCE_INSPECTED')
    assert len(inspection.payload['observations'])==8 and inspection.payload['matched_identity_and_order']
    assert all(inspection.payload['unique_ids_per_condition'].values())
    assert state_pin(after)!=state_pin(before)
    assert after.runs==before.runs and after.metrics==before.metrics and after.analyses==before.analyses
    context=ContextBuilder().build(after)
    assert context.current_records['existing_result_inspection']['matched_identity_and_order']
    run(orch.decide(PROJECT,max_repairs=0))

@pytest.mark.parametrize('damage',['raw','resource','bound'])
def test_local_inspection_rejects_changed_or_unbounded_inputs(reviewed,damage):
    from autolab.literature.result_inspection import inspect_result
    snapshot=snap(reviewed)
    if damage=='raw':Path(snapshot.runs[0].output_manifest['artifacts']['raw_outputs.jsonl']['path']).write_text('{}\n')
    elif damage=='resource':Path(snapshot.resources[0].path_or_uri).write_text('[]')
    else:
        # Explicit schema bound remains enforced before model/local inspection.
        snapshot=snapshot.model_copy(update={'hypotheses':[*snapshot.hypotheses,snapshot.hypotheses[-1].model_copy(update={'version':2})]})
    with pytest.raises(RuntimeError):inspect_result(snapshot)

@pytest.mark.parametrize('replication',[False,True])
def test_duplicate_selection_gate_and_justified_replication(reviewed,replication):
    before=snap(reviewed);spec=selected_experiment(before)
    from autolab.experiment_design.context import build_context
    assignments=[{'candidate_id':'CAND_REPEAT_'+str(i),'version':1,'project_id':PROJECT,
        'hypothesis_id':spec.hypothesis_id,'hypothesis_version':spec.hypothesis_version} for i in range(2)]
    batch=run(Designer(spec).generate(build_context(before),assignments))
    candidate=batch.candidates[0]
    design=dict(candidate.design);design['dataset_requirements']=dict(spec.dataset_requirements)
    if replication:design['dataset_requirements'].update(purpose='replication',replication_reason='Independent exact-protocol replication checks reproducibility')
    candidate=candidate.model_copy(update={'design':design})
    reviewed.add_experiment_candidate(candidate)
    reviewed.add_review(s.ReviewRecord(review_id=reviewed.next_id('ERREV'),project_id=PROJECT,review_type='experiment',
        target_type='experiment_candidates',target_id=candidate.candidate_id,reviewer_role='critic',verdict='PASS'))
    snapshot=snap(reviewed)
    assert DecisionValidator().validate(d(snapshot,'SELECT_EXPERIMENT','planner',[candidate.candidate_id]),snapshot).valid is replication


def test_pause_and_terminal_stop_halt_continue_without_pi(reviewed):
    reviewed.add_event(s.EventRecord(event_id=reviewed.next_id('EVENT'),project_id=PROJECT,event_type='PROJECT_PAUSED',actor='human',summary='Pause'))
    planner=Planner([]);orch=Orchestrator(reviewed,planner)
    assert run(orch.continue_research(PROJECT))['status']=='PAUSED' and planner.calls==0
    reviewed.add_decision(d(snap(reviewed),'STOP',None))
    reviewed.add_event(s.EventRecord(event_id=reviewed.next_id('EVENT'),project_id=PROJECT,event_type='PROJECT_RESUMED',actor='human',summary='Cannot undo STOP'))
    assert run(orch.continue_research(PROJECT))['status']=='COMPLETED' and planner.calls==0


def test_invalid_additional_round_proposal_preserved_as_blocked_event(reviewed):
    scope=snap(reviewed).authorized_scope
    # New linked scope, explicit human constraint; old charter is never edited.
    linked=reviewed.create_project(scope.model_copy(update={'project_id':'PROJECT_ONE_ROUND','constraints':{**scope.constraints,'max_rounds':1}}))
    reviewed.add_event(s.EventRecord(event_id=reviewed.next_id('EVENT'),project_id=PROJECT,event_type='LINKED_RESEARCH_SCOPE_AUTHORIZED',actor='human',summary='One-round hard cap',
        payload={'linked_project_id':linked.project_id,'parent_charter_fingerprint':fingerprint(snap(reviewed).charter),'linked_charter_fingerprint':fingerprint(linked)}))
    with pytest.raises(IllegalDecisionError):run(Orchestrator(reviewed,Planner(['RUN_FOLLOWUP'])).decide(PROJECT,max_repairs=0))
    assert any(e.event_type=='ROUND_LIMIT_REACHED' and e.payload['proposed_decision']['action']=='RUN_FOLLOWUP' for e in snap(reviewed).events)


def test_direct_followup_route_still_records_round_and_once_only_dispatch(reviewed):
    orch=Orchestrator(reviewed,Planner(['RUN_FOLLOWUP']))
    route=run(orch.decide(PROJECT,max_repairs=0))
    pipeline=ExperimentDesignPipeline(reviewed,Designer(selected_experiment(snap(reviewed))),DesignCritic())
    run(orch.execute_experiment_design(route,pipeline))
    assert round_count(snap(reviewed))==2
    with pytest.raises(IllegalDecisionError):run(orch.execute_experiment_design(route,pipeline))


def test_completed_round_records_second_result_not_parent_again(reviewed,tmp_path):
    from autolab.orchestration.adaptive import round_history
    # The full slice is a single reusable production-service test, no duplicated workflow.
    test_full_two_round_vertical_slice_reuses_every_downstream_service(reviewed,tmp_path)
    history=round_history(snap(reviewed))
    assert history[-1]['result']['parent_run_id']=='RUN_0002'
    assert history[-1]['result']['parent_analysis_id']=='ANALYSIS_0002'
    assert history[-1]['result']['ending_decision']


def test_replacement_generation_after_result_rejection_keeps_failed_branch(reviewed):
    from autolab.hypotheses.service import HypothesisPipeline
    from test_hypotheses import FakeAgent,FakeCritic
    orch=Orchestrator(reviewed,Planner(['REJECT_HYPOTHESIS','GENERATE_HYPOTHESES']))
    route=run(orch.decide(PROJECT,max_repairs=0));run(orch.execute_adaptive(route))
    before=snap(reviewed);agent=FakeAgent();pipeline=HypothesisPipeline(reviewed,agent,FakeCritic())
    route=run(orch.decide(PROJECT,max_repairs=0));run(orch.execute_adaptive(route,services={'hypothesis':pipeline}))
    after=snap(reviewed)
    assert len(after.hypotheses)==4 and after.hypotheses[0]==before.hypotheses[0]
    assert agent.contexts[0].rejected_hypotheses and agent.contexts[0].reviewed_result
    assert after.runs==before.runs and after.analyses==before.analyses


def test_direct_selection_of_reviewed_candidate_starts_bounded_next_round(reviewed):
    before=snap(reviewed)
    # Candidate creation/review here is explicitly an offline state fixture.
    run(ExperimentDesignPipeline(reviewed,Designer(selected_experiment(before)),DesignCritic()).generate(PROJECT))
    orch=Orchestrator(reviewed,Planner(['SELECT_EXPERIMENT']))
    run(orch.decide(PROJECT,max_repairs=0))
    after=snap(reviewed)
    assert round_count(after)==2
    selected=next(e for e in reversed(after.events) if e.event_type=='EXPERIMENT_SELECTED')
    assert selected.payload['round_id']=='ROUND_0002' and selected.payload['parent_run_id']=='RUN_0001'
