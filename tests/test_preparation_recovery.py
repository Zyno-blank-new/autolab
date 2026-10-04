"""Focused, offline A/B/C recovery and persisted-event rendering checks."""
import asyncio,json
from pathlib import Path
import pytest
from autolab import schemas as s
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import readiness_passes
from autolab.preparation.service import PreparationService
from autolab.preparation.models import PreparationError,ResourcePreparationPlan,IssueResponse
from autolab.preparation.manifest import current_plan,current_manifest,fingerprint,repair_attempts
from autolab.preparation.recovery import propose_successor,activate_successor,repair_in_plan
from autolab.readiness.service import ReadinessService
from autolab.feasibility.service import FeasibilityService
from autolab.feasibility.approval import ApprovalService
from autolab.feasibility.models import FeasibilityInputs,ResourceAccess,CostInput,EstimateRange
from autolab.event_stream import EventStream
from phase8_helpers import seed,requirement,Preparer,Auditor,run

@pytest.fixture
def checkpoint(ledger,tmp_path):
 p,e,registry=seed(ledger)
 prep=PreparationService(ledger,Preparer(),registry=registry,root=tmp_path)
 run(prep.prepare(p.project_id));run(ReadinessService(ledger,Auditor('REPAIR')).audit(p.project_id))
 return ledger,p,e,prep,registry

def successor_agent(prep,*,change=None):
 class Agent:
  async def plan(self,context,assignment,previous=None,issues=None):
   parent=previous.resource_requirements[0]
   addition=parent.model_copy(update={'requirement_id':'visible','acquisition_mode':'TRANSFORM','handler':'transform',
    'dependencies':[parent.requirement_id],'parameters':{'parent_requirement':parent.requirement_id,'operation':'project','fields':['id','text']},
    'criteria':parent.criteria.model_copy(update={'required_fields':['id','text'],'condition_field':None,'required_conditions':[],'label_field':None})})
   plan=ResourcePreparationPlan(**assignment,resource_requirements=[parent,addition],
    issue_responses=[IssueResponse(issue_index=i,disposition='ACCEPT',reason='Preserve the original contract; lossless visibility projection') for i in range(len(issues))])
   return change(plan) if change else plan
 prep.agent=Agent()

def reapprove(checkpoint):
 l,p,e,prep,registry=checkpoint
 inputs=FeasibilityInputs(resource_access=[ResourceAccess(requirement='Task inputs',status='AVAILABLE')],
  costs=[CostInput(category='Incremental local projection',unit_price_usd=1,units=EstimateRange(maximum=1))],
  runtime_minutes=EstimateRange(maximum=5),execution_risks=[],storage_gb=EstimateRange(maximum=.001))
 FeasibilityService(l,registry).assess(p.project_id,e.experiment_id,inputs)
 a=ApprovalService(l,allow_test_human=True);pkt=a.request_approval(p.project_id,e.experiment_id)
 a.record_human_decision(p.project_id,e.experiment_id,1,'APPROVE',packet_id=pkt.packet_id,actor='test-human',max_cost_usd=5,max_runtime_minutes=30,approved_actions=['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT'])

def test_in_plan_repair_preserves_plan_and_versions_resources(checkpoint):
 l,p,e,prep,_=checkpoint;before=load_snapshot(l,p.project_id);old=current_plan(before);old_manifest=current_manifest(before)
 result=repair_in_plan(prep,p.project_id,[{'issue_index':0,'disposition':'ACCEPT','reason':'Recreate malformed resource with the immutable handler/criteria'}])
 after=load_snapshot(l,p.project_id)
 assert fingerprint(current_plan(after))==fingerprint(old)
 assert current_manifest(after).manifest_id!=old_manifest.manifest_id
 assert len(after.resources)>len(before.resources) and after.resources[-1].version=='2'
 assert len([x for x in after.events if x.event_type=='PREPARATION_PLAN_CREATED'])==1
 assert not readiness_passes(after)
 audited=run(ReadinessService(l,Auditor()).audit(p.project_id))
 assert audited.metadata['repair_count']==1
 assert l.list_events(p.project_id)[-1].payload['repair_count']==1

@pytest.mark.parametrize('disposition',['REBUT','CLARIFY'])
def test_auditor_overreach_can_be_reassessed_without_new_resource(checkpoint,disposition):
 l,p,e,prep,_=checkpoint;snap=load_snapshot(l,p.project_id);plan=current_plan(snap)
 l.add_event(prep._event(p.project_id,'PREPARATION_REPAIR_RESPONSES',e,'Evidence-backed response',plan_id=plan.plan_id,plan_version=plan.version,
  responses=[{'issue_index':0,'disposition':disposition,'reason':'The requested future implementation is outside pre-implementation resource scope'}]))
 class Capture(Auditor):
  async def audit(self,c,a):
   assert c['repair_responses'][0]['disposition']==disposition
   return await super().audit(c,a)
 run(ReadinessService(l,Capture()).audit(p.project_id))
 assert readiness_passes(load_snapshot(l,p.project_id))

@pytest.mark.parametrize('mutation',[
 lambda x:x.model_copy(update={'resource_requirements':[x.resource_requirements[1]]}),
 lambda x:x.model_copy(update={'resource_requirements':[x.resource_requirements[0].model_copy(update={'criteria':x.resource_requirements[0].criteria.model_copy(update={'min_samples':1})}),x.resource_requirements[1]]}),
 lambda x:x.model_copy(update={'resource_requirements':[x.resource_requirements[0],x.resource_requirements[1].model_copy(update={'spec_requirements':['New scientific control']})]}),
 lambda x:x.model_copy(update={'resource_requirements':[x.resource_requirements[0],x.resource_requirements[1].model_copy(update={'required_capabilities':['new_paid_model']})]}),
 lambda x:x.model_copy(update={'resource_requirements':[x.resource_requirements[0],x.resource_requirements[1].model_copy(update={'parameters':{'parent_requirement':'inputs','operation':'split','fields':['id','text']}})]}),
])
def test_expansion_and_mutation_cannot_masquerade_as_omission(checkpoint,mutation):
 l,p,e,prep,_=checkpoint;old=fingerprint(current_plan(load_snapshot(l,p.project_id)));successor_agent(prep,change=mutation)
 with pytest.raises(PreparationError):run(propose_successor(prep,p.project_id))
 assert fingerprint(current_plan(load_snapshot(l,p.project_id)))==old

@pytest.mark.parametrize('price',[0,100])
def test_old_approval_never_authorizes_plan_omission(checkpoint,price):
 l,p,e,prep,_=checkpoint
 successor_agent(prep,change=lambda x:x.model_copy(update={'resource_requirements':[x.resource_requirements[0],x.resource_requirements[1].model_copy(update={'estimated_cost_usd':price})]}))
 event=run(propose_successor(prep,p.project_id))
 with pytest.raises(PreparationError,match='fresh incremental'):activate_successor(prep,p.project_id,event.event_id)
 assert current_plan(load_snapshot(l,p.project_id)).version==1


def test_successor_lineage_new_manifest_fresh_pass_and_isolation(checkpoint):
 l,p,e,prep,_=checkpoint;before=load_snapshot(l,p.project_id);old=current_plan(before);successor_agent(prep)
 event=run(propose_successor(prep,p.project_id));assert current_plan(load_snapshot(l,p.project_id))==old
 reapprove(checkpoint);activate_successor(prep,p.project_id,event.event_id)
 snap=load_snapshot(l,p.project_id);assert current_plan(snap).version==2 and not readiness_passes(snap)
 created=[x for x in snap.events if x.event_type=='PREPARATION_PLAN_CREATED']
 assert created[-1].payload['previous_plan_fingerprint']==fingerprint(old)
 assert created[0].payload['plan']==old.model_dump(mode='json')
 assert current_manifest(snap).plan_version==2 and len(current_manifest(snap).resources)==2
 run(ReadinessService(l,Auditor()).audit(p.project_id));assert readiness_passes(load_snapshot(l,p.project_id))
 assert l.get_project('PROJECT_0001') is None and all(r.project_id==p.project_id for r in snap.resources)


def test_material_cost_requires_approval_that_covers_it(checkpoint):
 l,p,e,prep,_=checkpoint;successor_agent(prep,change=lambda x:x.model_copy(update={'resource_requirements':[x.resource_requirements[0],x.resource_requirements[1].model_copy(update={'estimated_cost_usd':99})]}))
 event=run(propose_successor(prep,p.project_id));reapprove(checkpoint)
 with pytest.raises(PreparationError,match='blocked'):activate_successor(prep,p.project_id,event.event_id)
 assert current_plan(load_snapshot(l,p.project_id)).version==1


def test_rejected_attempts_do_not_reset_bound(checkpoint):
 l,p,e,prep,_=checkpoint
 for n in (1,2):l.add_event(prep._event(p.project_id,'RESOURCE_PREPARATION_STARTED',e,'Rejected repair',repair_attempt=n))
 successor_agent(prep)
 with pytest.raises(PreparationError,match='limit exhausted'):run(propose_successor(prep,p.project_id))
 assert repair_attempts(load_snapshot(l,p.project_id))==2
 assert run(prep.prepare(p.project_id)).repair_attempts==2


def test_event_stream_has_only_persisted_project_events_and_no_private_payload(checkpoint,tmp_path,monkeypatch,capsys):
 l,p,e,prep,_=checkpoint;monkeypatch.setenv('OPENAI_API_KEY','private-test-value')
 l.add_event(s.EventRecord(event_id=l.next_id('EVENT'),project_id=p.project_id,event_type='PLANNER_DECISION',actor='planner',target_type='decisions',target_id='DEC_TEST',summary='private-test-value',payload={'action':'STOP','prompt':'private-test-value','reasoning':'never render'}))
 stream=EventStream(p.project_id,tmp_path/'events.log');lines=stream.refresh(l)
 assert len(lines)==len(l.list_events(p.project_id)) and stream.refresh(l)==[]
 text=(tmp_path/'events.log').read_text();assert 'private-test-value' not in text and 'never render' not in text
 assert '[planner] → STOP' in text and 'event=' in text and '[' in text
 assert set(x.rsplit(' event=',1)[1] for x in lines)=={e.event_id for e in l.list_events(p.project_id)}


def test_exhaustion_is_deterministic_block_and_preserves_independent_review(checkpoint):
 l,p,e,prep,_=checkpoint;snapshot=load_snapshot(l,p.project_id);prior=snapshot.readiness[-1]
 with pytest.raises(PreparationError,match='two consumed'):ReadinessService(l,Auditor()).record_exhausted(p.project_id,prior)
 for n in (1,2):l.add_event(prep._event(p.project_id,'RESOURCE_PREPARATION_STARTED',e,'Rejected repair',repair_attempt=n))
 result=ReadinessService(l,Auditor()).record_exhausted(p.project_id,prior)
 assert result.verdict=='BLOCK' and result.metadata['repair_count']==2
 assert result.metadata['original_independent_readiness_id']==prior.readiness_id
 assert 'no new independent model audit' in result.metadata['verdict_origin']
 assert l.get(s.ReadinessReport,prior.readiness_id)==prior
 assert not readiness_passes(load_snapshot(l,p.project_id))


def test_scientific_expansion_persists_block_without_spec_change(checkpoint):
 l,p,e,prep,_=checkpoint;original=l.get(s.ExperimentSpec,e.experiment_id)
 successor_agent(prep,change=lambda x:x.model_copy(update={'resource_requirements':[x.resource_requirements[0],x.resource_requirements[1].model_copy(update={'required_capabilities':['unapproved_training']})]}))
 with pytest.raises(PreparationError,match='Scientific expansion'):run(propose_successor(prep,p.project_id))
 blocks=[x for x in l.list_events(p.project_id) if x.event_type=='RESOURCE_PREPARATION_BLOCKED']
 assert blocks[-1].payload['repair_class']=='C' and blocks[-1].payload['status']=='BLOCK'
 assert l.get(s.ExperimentSpec,e.experiment_id)==original
