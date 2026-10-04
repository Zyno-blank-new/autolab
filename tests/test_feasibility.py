"""Phase 7 gates, estimates, provenance and persistence; no API or preparation."""
import asyncio
from datetime import timedelta

import pytest
from pydantic import ValidationError

from autolab import schemas as s
from autolab.feasibility.approval import ApprovalService, render_packet
from autolab.feasibility.capability_registry import CapabilityRegistry
from autolab.feasibility.cost_estimator import budget_status, estimate_cost, time_status
from autolab.feasibility.models import (
    BudgetStatus as B, Capability, CapabilityStatus as S, Complexity, CostInput, EstimateRange,
    FeasibilityInputs, FeasibilityStatus as F, ResourceAccess, TimeStatus as T,
)
from autolab.feasibility.persistence import current_assessment, current_packet
from autolab.feasibility.service import FeasibilityError, FeasibilityService
from autolab.ledger import ResearchLedger
from autolab.orchestration.budget import calculate_budget, calculate_time
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import approval_for, derive_control_state


@pytest.fixture
def selected(ledger):
    p = ledger.create_project(s.ResearchCharter(project_id='PROJECT_TEST', title='Explicit planning fixture',
        research_question='Does policy A change task success?', objective='Compare controlled policies',
        primary_outcome='Task success', budget_usd=10, max_runtime_minutes=60))
    h = ledger.add_hypothesis(s.Hypothesis(hypothesis_id='HYP_TEST', project_id=p.project_id,
        statement='Policy A improves controlled task success', falsifiable_prediction='Positive paired success difference'))
    e = ledger.add_experiment_spec(s.ExperimentSpec(experiment_id='EXP_TEST', project_id=p.project_id,
        hypothesis_id=h.hypothesis_id, title='Planning test', objective='Compare paired success',
        experiment_type='paired comparison', primary_metric='paired success difference',
        success_criteria={'scientific':'Adequate paired interval above zero'},
        falsification_criteria={'scientific':'Adequate interval excludes benefit'},
        required_capabilities=['python_execution'], required_resources=['Declared test input'],
        estimated_cost_usd=None, estimated_runtime_minutes=None))
    ledger.add_review(s.ReviewRecord(review_id='HREV_TEST', project_id=p.project_id, target_type='experiments',
        target_id=e.experiment_id, review_type='experiment', verdict='PASS', reviewer_role='critic'))
    ledger.add_event(s.EventRecord(event_id='EVENT_SELECTION', project_id=p.project_id, event_type='EXPERIMENT_SELECTED',
        actor='planner', target_type='experiments', target_id=e.experiment_id, summary='Test selection',
        payload={'experiment_id':e.experiment_id,'version':1,'reason':'An informative paired comparison'}))
    return p, e


@pytest.fixture
def inputs():
    return FeasibilityInputs(resource_access=[ResourceAccess(requirement='Declared test input',status=S.AVAILABLE)],
        costs=[CostInput(category='configured test cost', units=EstimateRange(minimum=1,expected=2,maximum=3),
            unit_price_usd=1, unit='test unit', confidence=0.5,
            assumptions=['Illustrative explicit test configuration, not real provider pricing'])],
        runtime_minutes=EstimateRange(minimum=1,expected=2,maximum=3),
        runtime_assumptions=['Illustrative total preparation + implementation + execution duration'],
        compute_requirements=['Local CPU test assumption'], storage_gb=EstimateRange(minimum=0,expected=0,maximum=0),
        implementation_complexity=Complexity.LOW)


def registry(status=S.AVAILABLE, **extra):
    return CapabilityRegistry([Capability(capability_id='python_execution',status=status,**extra)])


def assessed(ledger, selected, inputs, *, status=S.AVAILABLE, **kwargs):
    p,e=selected
    return FeasibilityService(ledger, registry(status)).assess(p.project_id,e.experiment_id,inputs,**kwargs)


def preparation(snapshot, action='PREPARE_RESOURCES'):
    return s.NextDecision(decision_id='DEC_TEST',project_id=snapshot.charter.project_id,action=action,
        target_agent='preparation',reason='Pursue reviewed approved protocol',
        remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd)


def approve(ledger, selected, *, decision='APPROVE', **kwargs):
    p,e=selected
    service=ApprovalService(ledger,allow_test_human=True)
    packet=service.request_approval(p.project_id,e.experiment_id)
    event=service.record_human_decision(p.project_id,e.experiment_id,e.version,decision,
        packet_id=packet.packet_id,actor='test-human',**kwargs)
    return packet,event


@pytest.mark.parametrize('status',list(S))
def test_capability_statuses_and_extensible_ids(status):
    value=CapabilityRegistry([Capability(capability_id='custom.vendor.feature',status=status)])
    assert value.get('custom.vendor.feature').status==status
    assert value.get('unconfigured').status==S.UNKNOWN
    assert len(value.check(['custom.vendor.feature','unconfigured','custom.vendor.feature']))==2
    with pytest.raises(ValueError): value.register(value.get('custom.vendor.feature'))


@pytest.mark.parametrize('has_key',[True,False])
def test_local_registry_only_checks_configuration(tmp_path,has_key):
    value=CapabilityRegistry.local(tmp_path,{'OPENAI_API_KEY':'private-test-value' if has_key else ''})
    assert value.get('python_execution').status==S.AVAILABLE
    assert value.get('openai_api').status==(S.AVAILABLE if has_key else S.REQUIRES_CREDENTIAL)
    assert value.get('network_access').status==S.UNKNOWN
    assert value.get('local_gpu').status==S.UNKNOWN
    assert 'private-test-value' not in value.get('openai_api').model_dump_json()


@pytest.mark.parametrize('capability,verdict',[(S.AVAILABLE,F.FEASIBLE),(S.UNAVAILABLE,F.BLOCKED),
    (S.REQUIRES_CREDENTIAL,F.NEEDS_USER_INPUT),(S.UNKNOWN,F.NEEDS_USER_INPUT)])
def test_feasibility_verdicts_for_required_capability(ledger,selected,inputs,capability,verdict):
    result=assessed(ledger,selected,inputs,status=capability)
    assert result.status==verdict
    assert bool(result.blockers)==(capability==S.UNAVAILABLE)
    assert result.available_capabilities==(['python_execution'] if capability==S.AVAILABLE else [])
    assert result.missing_capabilities==([] if capability==S.AVAILABLE else ['python_execution'])


def test_warning_is_not_a_blocker(ledger,selected,inputs):
    result=assessed(ledger,selected,inputs.model_copy(update={'warnings':['Acquisition size needs verification']}))
    assert result.status==F.FEASIBLE_WITH_WARNINGS and not result.blockers and not result.user_input_required


@pytest.mark.parametrize('status',[S.UNKNOWN,S.REQUIRES_CREDENTIAL,S.UNAVAILABLE])
def test_resource_access_preserves_missing_requirement(ledger,selected,inputs,status):
    inputs=inputs.model_copy(update={'resource_access':[ResourceAccess(requirement='Declared test input',status=status)]})
    result=assessed(ledger,selected,inputs)
    assert result.unresolved_resource_requirements==['Declared test input']
    assert result.status==(F.BLOCKED if status==S.UNAVAILABLE else F.NEEDS_USER_INPUT)
    assert not ledger.list_resources(selected[0].project_id)


def test_missing_resource_declaration_needs_input(ledger,selected,inputs):
    result=assessed(ledger,selected,inputs.model_copy(update={'resource_access':[]}))
    assert result.status==F.NEEDS_USER_INPUT and result.user_input_required


def test_mapping_and_credential_requirements_are_explicit(ledger,selected,inputs):
    p,e=selected
    cap=Capability(capability_id='provider.inference',status=S.REQUIRES_CREDENTIAL,
        provider='test provider',credential_requirement='TEST_API_KEY',cost_driver='provider calls')
    data=inputs.model_copy(update={'capability_mapping':{'python_execution':['provider.inference']},
        'external_api_requirements':['provider.inference']})
    result=FeasibilityService(ledger,CapabilityRegistry([cap])).assess(p.project_id,e.experiment_id,data)
    assert result.credential_requirements==['TEST_API_KEY'] and result.external_api_requirements==['provider.inference']
    assert result.cost.unknown_cost_drivers and result.status==F.NEEDS_USER_INPUT
    assert result.required_capabilities==['provider.inference']


def test_explicit_costs_aggregate_with_ranges(inputs):
    cost=estimate_cost(inputs.costs+[CostInput(category='compute',units=EstimateRange(minimum=2,expected=3,maximum=4),
        unit_price_usd=2,unit='test hour',confidence=0.7)])
    assert cost.estimate_usd==EstimateRange(minimum=5,expected=8,maximum=11)
    assert cost.confidence==0.5 and not cost.unknown_cost_drivers


def test_unknown_prices_are_not_zero_or_an_invented_total(inputs):
    cost=estimate_cost(inputs.costs+[CostInput(category='unpriced inference',units=EstimateRange(minimum=1,maximum=5))])
    assert cost.estimate_usd.maximum is None and cost.estimate_usd.expected is None
    assert cost.unknown_cost_drivers and cost.categories[0].estimate_usd.maximum==3
    assert estimate_cost([],spec_estimate=0).unknown_cost_drivers


@pytest.mark.parametrize('values',[(3,2,1),(-1,0,2),(0,1,float('inf'))])
def test_invalid_ranges_rejected(values):
    with pytest.raises(ValidationError): EstimateRange(minimum=values[0],expected=values[1],maximum=values[2])


@pytest.mark.parametrize('bounds,remaining,expected',[(EstimateRange(minimum=1,maximum=3),5,B.WITHIN_BUDGET),
    (EstimateRange(minimum=1,maximum=8),5,B.POSSIBLY_WITHIN_BUDGET),
    (EstimateRange(minimum=6,maximum=8),5,B.OVER_BUDGET),(EstimateRange(),5,B.UNKNOWN)])
def test_budget_range_status(bounds,remaining,expected):
    assert budget_status(bounds,remaining)==expected


@pytest.mark.parametrize('bounds,remaining,expected',[(EstimateRange(minimum=1,maximum=3),5,T.WITHIN_TIME),
    (EstimateRange(minimum=1,maximum=8),5,T.AT_RISK),(EstimateRange(minimum=6,maximum=8),5,T.OVER_TIME),
    (EstimateRange(),5,T.UNKNOWN),(EstimateRange(maximum=3),None,T.WITHIN_TIME)])
def test_time_range_status(bounds,remaining,expected):
    assert time_status(bounds,remaining)==expected


def test_estimates_never_become_actual_spend(ledger,selected,inputs):
    p,e=selected
    ledger.add_cost(s.CostRecord(cost_id='COST_ACTUAL',project_id=p.project_id,category='past',actual_usd=2))
    result=assessed(ledger,selected,inputs)
    snapshot=load_snapshot(ledger,p.project_id)
    assert result.remaining_budget_usd==8 and calculate_budget(snapshot).remaining_budget_usd==8
    assert calculate_budget(snapshot).actual_spent_usd==2
    cost=next(c for c in snapshot.costs if c.metadata.get('assessment_id')==result.assessment_id)
    assert cost.actual_usd==0 and cost.metadata['actual_known'] is False
    assert cost.metadata['estimate_usd']=={'minimum':1.0,'expected':2.0,'maximum':3.0}


@pytest.mark.parametrize('driver',['budget','time'])
def test_definite_limit_violation_blocks_assessment(ledger,selected,inputs,driver):
    if driver=='budget': inputs=inputs.model_copy(update={'costs':[CostInput(category='expensive',units=EstimateRange(minimum=11,maximum=20),unit_price_usd=1)]})
    else: inputs=inputs.model_copy(update={'runtime_minutes':EstimateRange(minimum=61,maximum=90)})
    result=assessed(ledger,selected,inputs)
    assert result.status==F.BLOCKED and result.blockers
    with pytest.raises(FeasibilityError): approve(ledger,selected)
    snap=load_snapshot(ledger,selected[0].project_id)
    assert not DecisionValidator().validate(preparation(snap),snap).valid


def test_remaining_time_uses_charter_elapsed_time(ledger,selected,inputs):
    p,e=selected
    result=assessed(ledger,selected,inputs,now=p.created_at+timedelta(minutes=5))
    assert result.remaining_time_minutes==55 and result.runtime_minutes.maximum==3
    assert calculate_time(load_snapshot(ledger,p.project_id),p.created_at+timedelta(minutes=5)).remaining_minutes==55


def test_approval_packet_and_scope_make_preparation_eligible(ledger,selected,inputs):
    p,e=selected
    before=load_snapshot(ledger,p.project_id)
    assert not DecisionValidator().validate(preparation(before),before).valid
    assessment=assessed(ledger,selected,inputs)
    snap=load_snapshot(ledger,p.project_id)
    assert derive_control_state(snap).value=='AWAITING_HUMAN_APPROVAL'
    assert not DecisionValidator().validate(preparation(snap),snap).valid
    packet,event=approve(ledger,selected,note='Pursue this reviewed exact version')
    snap=load_snapshot(ledger,p.project_id)
    assert packet.assessment_id==assessment.assessment_id and packet.experiment_version==1
    assert event.actor=='test-human' and event.event_type=='HUMAN_APPROVED'
    scope=approval_for(snap,s.PlannerAction.PREPARE_RESOURCES)
    assert scope and scope.experiment_version==1 and scope.assessment_id==assessment.assessment_id
    assert DecisionValidator().validate(preparation(snap),snap).valid
    assert derive_control_state(snap).value=='RESOURCE_PREPARATION'
    assert ledger.get_experiment(e.experiment_id)==e
    assert not snap.resources and not snap.implementations and not snap.runs
    rendered=render_packet(packet)
    assert 'EXP_TEST v1' in rendered and '$1–$3 (estimate)' in rendered
    assert 'Remaining project budget: $10' in rendered and 'not scientific proof' in rendered


@pytest.mark.parametrize('decision',['REJECT','MODIFY'])
def test_negative_decisions_revoke_approval_and_preserve_science(ledger,selected,inputs,decision):
    p,e=selected
    assessed(ledger,selected,inputs); approve(ledger,selected)
    _,event=approve(ledger,selected,decision=decision,note='Reconsider before pursuing')
    snap=load_snapshot(ledger,p.project_id)
    assert event.event_type==('HUMAN_REJECTED' if decision=='REJECT' else 'HUMAN_MODIFICATION_REQUESTED')
    assert approval_for(snap,s.PlannerAction.PREPARE_RESOURCES) is None
    assert not DecisionValidator().validate(preparation(snap),snap).valid
    assert derive_control_state(snap).value=='ADAPTIVE_DECISION'
    assert ledger.get_experiment(e.experiment_id)==e


@pytest.mark.parametrize('actor',['planner','critic','agent','LLM','AUTO_APPROVED'])
def test_agent_cannot_record_human_decision(ledger,selected,inputs,actor):
    p,e=selected;assessed(ledger,selected,inputs)
    service=ApprovalService(ledger);packet=service.request_approval(p.project_id,e.experiment_id)
    with pytest.raises(ValidationError):
        service.record_human_decision(p.project_id,e.experiment_id,1,'APPROVE',packet_id=packet.packet_id,actor=actor)
    assert not any(v.event_type=='HUMAN_APPROVED' for v in ledger.list_events(p.project_id))


def test_test_human_not_accepted_by_production_service(ledger,selected,inputs):
    p,e=selected;assessed(ledger,selected,inputs)
    service=ApprovalService(ledger);packet=service.request_approval(p.project_id,e.experiment_id)
    with pytest.raises(FeasibilityError,match='Test-human'):
        service.record_human_decision(p.project_id,e.experiment_id,1,'APPROVE',packet_id=packet.packet_id,actor='test-human')


@pytest.mark.parametrize('change',['version','assessment','packet'])
def test_approval_invalidation_is_exact_and_fail_closed(ledger,selected,inputs,change):
    p,e=selected;assessed(ledger,selected,inputs);packet,_=approve(ledger,selected)
    if change=='version': ledger.add_experiment_spec(e.model_copy(update={'version':2,'objective':'Explicit later amendment'}))
    elif change=='assessment': assessed(ledger,selected,inputs.model_copy(update={'warnings':['New material risk']}))
    else: ApprovalService(ledger).request_approval(p.project_id,e.experiment_id)
    snap=load_snapshot(ledger,p.project_id)
    assert approval_for(snap,s.PlannerAction.PREPARE_RESOURCES) is None
    assert not DecisionValidator().validate(preparation(snap),snap).valid
    with pytest.raises(FeasibilityError):
        ApprovalService(ledger).record_human_decision(p.project_id,e.experiment_id,1,'APPROVE',packet_id=packet.packet_id)


@pytest.mark.parametrize('case',['wrong_experiment','wrong_version','wrong_project','malformed_decision','malformed_cap'])
def test_invalid_human_input_does_not_create_approval(ledger,selected,inputs,case):
    p,e=selected;assessed(ledger,selected,inputs)
    service=ApprovalService(ledger);packet=service.request_approval(p.project_id,e.experiment_id)
    args=[p.project_id,e.experiment_id,1,'APPROVE']
    if case=='wrong_experiment':args[1]='EXP_OTHER'
    if case=='wrong_version':args[2]=2
    if case=='wrong_project':args[0]='PROJECT_OTHER'
    if case=='malformed_decision':args[3]='AUTO_APPROVED'
    kwargs={'max_cost_usd':-1} if case=='malformed_cap' else {}
    with pytest.raises((FeasibilityError,ValidationError,KeyError)):
        service.record_human_decision(*args,packet_id=packet.packet_id,**kwargs)
    assert not any(v.event_type=='HUMAN_APPROVED' for v in ledger.list_events(p.project_id))


def test_unknown_cost_can_be_acknowledged_without_fake_estimate(ledger,selected,inputs):
    p,e=selected
    data=inputs.model_copy(update={'costs':[CostInput(category='unknown provider')],'runtime_minutes':None})
    result=assessed(ledger,selected,data)
    assert result.status==F.FEASIBLE_WITH_WARNINGS and result.budget_status==B.UNKNOWN
    assert result.cost.estimate_usd.maximum is None and result.runtime_minutes.maximum is None
    with pytest.raises(FeasibilityError,match='acknowledge'):
        approve(ledger,selected,max_cost_usd=3,max_runtime_minutes=5)
    with pytest.raises(FeasibilityError,match='maximum'):
        approve(ledger,selected,acknowledge_unknowns=True)
    approve(ledger,selected,max_cost_usd=3,max_runtime_minutes=5,acknowledge_unknowns=True)
    snap=load_snapshot(ledger,p.project_id)
    assert DecisionValidator().validate(preparation(snap),snap).valid
    assert current_assessment(snap).cost.estimate_usd.maximum is None
    assert calculate_budget(snap).actual_spent_usd==0


@pytest.mark.parametrize('change',[{'max_cost_usd':2},{'max_cost_usd':11},{'max_runtime_minutes':1},{'max_runtime_minutes':100}])
def test_human_caps_cannot_override_known_bounds_or_charter(ledger,selected,inputs,change):
    assessed(ledger,selected,inputs)
    with pytest.raises(FeasibilityError): approve(ledger,selected,**change)


def test_persistence_and_restart_preserve_assessment_cost_packet_approval(ledger,selected,inputs):
    p,e=selected
    assessment=assessed(ledger,selected,inputs);packet,event=approve(ledger,selected)
    before=load_snapshot(ledger,p.project_id)
    with ResearchLedger(ledger.database.path) as reopened:
        snap=load_snapshot(reopened,p.project_id)
        assert snap==before and current_assessment(snap)==assessment and current_packet(snap)==packet
        assert reopened.get(s.EventRecord,event.event_id)==event
        assert DecisionValidator().validate(preparation(snap),snap).valid
        assert {'FEASIBILITY_ASSESSMENT_STARTED','FEASIBILITY_ASSESSED','COST_ESTIMATE_CREATED',
            'HUMAN_APPROVAL_REQUESTED','HUMAN_APPROVED'} <= {x.event_type for x in snap.events}


def test_context_is_concise_and_decision_is_still_adaptive(ledger,selected,inputs):
    p,e=selected;assessed(ledger,selected,inputs);approve(ledger,selected)
    context=ContextBuilder().build(load_snapshot(ledger,p.project_id))
    assert context.current_records['feasibility']['status']=='FEASIBLE'
    assert context.current_records['human_approval']['scope_current'] is True
    assert s.PlannerAction.PREPARE_RESOURCES in context.available_actions
    class Planner:
        async def propose(self,c,decision_id,feedback=None):
            return s.NextDecision(decision_id=decision_id,project_id=p.project_id,action='GATHER_EVIDENCE',
                target_agent='evidence',reason='Check an informative alternative',remaining_budget_usd=10).model_dump_json()
    route=asyncio.run(Orchestrator(ledger,Planner()).decide(p.project_id))
    assert route.action==s.PlannerAction.GATHER_EVIDENCE
    assert not ledger.list_resources(p.project_id) and not ledger.list_runs(p.project_id)


def test_failed_assessment_is_atomic_and_does_not_damage_science(ledger,selected,inputs):
    p,e=selected;old=assessed(ledger,selected,inputs)
    costs=ledger.list_costs(p.project_id)
    bad=inputs.model_copy(update={'resource_access':[ResourceAccess(requirement='foreign requirement')]})
    with pytest.raises(FeasibilityError):assessed(ledger,selected,bad)
    snap=load_snapshot(ledger,p.project_id)
    assert current_assessment(snap)==old and snap.costs==costs and ledger.get_experiment(e.experiment_id)==e
    assert snap.events[-1].event_type=='FEASIBILITY_ASSESSMENT_FAILED'


def test_secrets_cannot_enter_approval_or_assessment(ledger,selected,inputs,monkeypatch):
    p,e=selected;monkeypatch.setenv('OPENAI_API_KEY','test-secret-only-credential')
    with pytest.raises(ValueError,match='Credential values'):
        assessed(ledger,selected,inputs.model_copy(update={'warnings':['test-secret-only-credential']}))
    assessed(ledger,selected,inputs)
    with pytest.raises(ValueError,match='Credential values'):
        approve(ledger,selected,note='test-secret-only-credential')
    assert all('test-secret-only-credential' not in ev.model_dump_json() for ev in ledger.list_events(p.project_id))


def test_capability_dependencies_are_aggregated_and_cycles_are_bounded():
    value=CapabilityRegistry([
        Capability(capability_id='api',status='AVAILABLE',requires_capabilities=['network']),
        Capability(capability_id='network',status='UNAVAILABLE',requires_capabilities=['api'])])
    assert [(c.capability_id,c.status.value) for c in value.check(['api'])]==[('api','AVAILABLE'),('network','UNAVAILABLE')]


def test_unknown_required_dependency_is_visible(ledger,selected,inputs):
    reg=CapabilityRegistry([Capability(capability_id='python_execution',status='AVAILABLE',requires_capabilities=['custom_runtime'])])
    result=FeasibilityService(ledger,reg).assess(selected[0].project_id,selected[1].experiment_id,inputs)
    assert result.missing_capabilities==['custom_runtime'] and result.status==F.NEEDS_USER_INPUT


def test_new_spec_version_requires_its_own_assessment_review_and_human_decision(ledger,selected,inputs):
    p,e=selected;assessed(ledger,selected,inputs);approve(ledger,selected)
    changed=ledger.add_experiment_spec(e.model_copy(update={'version':2,'controls':{'new_control':'Explicit reviewed amendment'}}))
    ledger.add_event(s.EventRecord(event_id='EVENT_V2_SELECTION',project_id=p.project_id,event_type='EXPERIMENT_SELECTED',
        actor='planner',target_type='experiments',target_id=e.experiment_id,summary='Explicit exact-version reselection',
        payload={'experiment_id':e.experiment_id,'version':2}))
    with pytest.raises(FeasibilityError,match='PASS'):assessed(ledger,(p,changed),inputs)
    ledger.add_review(s.ReviewRecord(review_id='HREV_V2',project_id=p.project_id,target_type='experiments',target_id=e.experiment_id,
        target_version=2,review_type='experiment',verdict='PASS',reviewer_role='critic'))
    assessed(ledger,(p,changed),inputs)
    snap=load_snapshot(ledger,p.project_id)
    assert not DecisionValidator().validate(preparation(snap),snap).valid
    approve(ledger,(p,changed))
    snap=load_snapshot(ledger,p.project_id)
    assert DecisionValidator().validate(preparation(snap),snap).valid
    assert approval_for(snap,s.PlannerAction.PREPARE_RESOURCES).experiment_version==2
    assert ledger.get_experiment(e.experiment_id,version=1)==e


@pytest.mark.parametrize('action',['APPROVE','REJECT','MODIFY'])
def test_minimal_cli_records_only_explicit_human_choice(ledger,selected,inputs,capsys,action):
    from autolab.approval import main
    p,e=selected;assessed(ledger,selected,inputs)
    packet=ApprovalService(ledger).request_approval(p.project_id,e.experiment_id)
    args=['--db',str(ledger.database.path),'decide','--project',p.project_id,'--experiment',e.experiment_id,
          '--version','1','--packet',packet.packet_id,'--decision',action,'--note','Explicit CLI test choice']
    main(args)
    snap=load_snapshot(ledger,p.project_id)
    response=snap.events[-1]
    assert response.actor=='human'
    assert response.event_type=={'APPROVE':'HUMAN_APPROVED','REJECT':'HUMAN_REJECTED','MODIFY':'HUMAN_MODIFICATION_REQUESTED'}[action]
    assert not snap.resources and not snap.implementations and not snap.runs
    assert 'Control returns to Planner' in capsys.readouterr().out


def test_show_packet_never_automatically_approves(ledger,selected,inputs,capsys):
    from autolab.approval import main
    p,e=selected;assessed(ledger,selected,inputs)
    packet=ApprovalService(ledger).request_approval(p.project_id,e.experiment_id)
    before=load_snapshot(ledger,p.project_id)
    main(['--db',str(ledger.database.path),'show','--project',p.project_id,'--experiment',e.experiment_id,'--version','1'])
    assert load_snapshot(ledger,p.project_id)==before
    assert f'Packet: {packet.packet_id}' in capsys.readouterr().out


def test_actual_cost_and_elapsed_time_can_revoke_eligibility(ledger,selected,inputs):
    p,e=selected;assessed(ledger,selected,inputs);approve(ledger,selected)
    snap=load_snapshot(ledger,p.project_id)
    assert not DecisionValidator().validate(preparation(snap),snap,now=p.created_at+timedelta(minutes=59)).valid
    ledger.add_cost(s.CostRecord(cost_id='COST_LATER_ACTUAL',project_id=p.project_id,category='known spend',actual_usd=8))
    snap=load_snapshot(ledger,p.project_id)
    assert not DecisionValidator().validate(preparation(snap),snap).valid


def test_legacy_human_approval_cannot_bypass_phase7_assessment(ledger,selected):
    p,e=selected
    ledger.add_event(s.EventRecord(event_id='EVENT_LEGACY',project_id=p.project_id,event_type='HUMAN_APPROVED',actor='human',
        summary='Historical unassessed approval',payload={'experiment_id':e.experiment_id,'experiment_version':1,
        'approved_actions':['PREPARE_RESOURCES'],'max_cost_usd':10,'max_runtime_minutes':10}))
    snap=load_snapshot(ledger,p.project_id)
    assert approval_for(snap,s.PlannerAction.PREPARE_RESOURCES) is None
    assert not DecisionValidator().validate(preparation(snap),snap).valid


@pytest.mark.parametrize('field,value',[
    ('experiment_id','EXP_OTHER'),('assessment_id','FEAS_OTHER'),
    ('assessment_version',2),('spec_fingerprint','wrong-fingerprint')])
def test_inconsistent_packet_bindings_fail_closed(ledger,selected,inputs,field,value):
    p,e=selected;assessed(ledger,selected,inputs)
    service=ApprovalService(ledger)
    packet=service.request_approval(p.project_id,e.experiment_id)
    corrupted=packet.model_dump(mode='json');corrupted[field]=value
    ledger.add_event(s.EventRecord(event_id='EVENT_BAD_PACKET',project_id=p.project_id,
        event_type='HUMAN_APPROVAL_REQUESTED',actor='approval',target_type='experiments',target_id=e.experiment_id,
        summary='Imported inconsistent packet',payload={'packet':corrupted}))
    snap=load_snapshot(ledger,p.project_id)
    assert current_packet(snap) is None
    with pytest.raises(FeasibilityError,match='missing/stale'):
        service.record_human_decision(p.project_id,e.experiment_id,e.version,'APPROVE',packet_id=packet.packet_id)
    assert not DecisionValidator().validate(preparation(snap),snap).valid
