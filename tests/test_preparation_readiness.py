"""Phase 8 gates, data handlers and independent audit mechanics, strictly offline."""
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import readiness_passes, derive_control_state
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.orchestrator import Orchestrator, IllegalDecisionError
from autolab.preparation.service import PreparationService
from autolab.preparation.models import PreparationError, ResourcePreparationPlan, ResourceManifest, IssueResponse
from autolab.preparation.manifest import current_plan, current_manifest, checksum, manifest_errors, fingerprint
from autolab.readiness.service import ReadinessService
from autolab.readiness.validators import ValidatorRegistry
from autolab.feasibility.models import Capability
from autolab.feasibility.capability_registry import CapabilityRegistry
from phase8_helpers import seed, requirement, criteria, Preparer, Auditor, run


@pytest.fixture
def setup(ledger,tmp_path):
    p,e,registry=seed(ledger)
    prep=PreparationService(ledger,Preparer(),registry=registry,root=tmp_path)
    audit=ReadinessService(ledger,Auditor())
    return p,e,prep,audit


def decision(snapshot,action='IMPLEMENT_EXPERIMENT',target='implementer'):
    return s.NextDecision(decision_id='DEC_CHECK',project_id=snapshot.charter.project_id,action=action,
        target_agent=target,reason='Check exact gated boundary',remaining_budget_usd=snapshot.charter.budget_usd)


def prepared(setup):
    p,e,prep,audit=setup; result=run(prep.prepare(p.project_id)); return result,load_snapshot(prep.ledger,p.project_id)


@pytest.mark.parametrize('approval',[False,True])
def test_exact_approval_required(ledger,tmp_path,approval):
    p,e,reg=seed(ledger,approval=approval)
    service=PreparationService(ledger,Preparer(),registry=reg,root=tmp_path)
    if approval: assert run(service.prepare(p.project_id)).status=='PREPARED'
    else:
        with pytest.raises(PreparationError,match='not authorized'): run(service.prepare(p.project_id))
        assert not ledger.list_resources(p.project_id) and service.agent.calls==0


@pytest.mark.parametrize('change',['spec','assessment','human_reject','human_modify'])
def test_stale_approval_rejected(ledger,tmp_path,change):
    p,e,reg=seed(ledger)
    if change=='spec': ledger.add_experiment_spec(e.model_copy(update={'version':2}))
    elif change=='assessment':
        ev=next(x for x in reversed(ledger.list_events(p.project_id)) if x.event_type=='FEASIBILITY_ASSESSED')
        data=ev.payload['assessment']; data={**data,'assessment_id':'FEAS_CHANGED'}
        ledger.add_event(ev.model_copy(update={'event_id':ledger.next_id('EVENT'),'created_at':s.utc_now(),'payload':{'assessment':data}}))
    else:
        ev=ledger.list_events(p.project_id)[-1]; kind='HUMAN_REJECTED' if change=='human_reject' else 'HUMAN_MODIFICATION_REQUESTED'
        ledger.add_event(ev.model_copy(update={'event_id':ledger.next_id('EVENT'),'created_at':s.utc_now(),'event_type':kind}))
    with pytest.raises(PreparationError): run(PreparationService(ledger,Preparer(),registry=reg,root=tmp_path).prepare(p.project_id))
    assert not ledger.list_resources(p.project_id)


def test_plan_acceptance_recorded_before_creation(setup):
    result,snapshot=prepared(setup); plan=current_plan(snapshot)
    assert plan.resource_requirements[0].spec_requirements==['Task inputs']
    events=[e.event_type for e in snapshot.events]
    assert events.index('PREPARATION_PLAN_CREATED')<events.index('RESOURCE_GENERATED')
    assert snapshot.resources[0].metadata['criteria']==plan.resource_requirements[0].criteria.model_dump(mode='json')


@pytest.mark.parametrize('status,expected',[('UNAVAILABLE','BLOCK'),('UNKNOWN','NEEDS_USER_INPUT'),('REQUIRES_CREDENTIAL','NEEDS_USER_INPUT'),('AVAILABLE','PREPARED')])
def test_capability_gates_before_actions(setup,status,expected):
    p,e,prep,audit=setup
    prep.registry=CapabilityRegistry([Capability(capability_id='filesystem_access',status=status,credential_requirement='AUTOLAB_TEST_MISSING' if status=='REQUIRES_CREDENTIAL' else None)])
    result=run(prep.prepare(p.project_id)); assert result.status==expected
    assert bool(prep.ledger.list_resources(p.project_id))==(status=='AVAILABLE')


def test_available_credential_requires_secure_configuration(setup,monkeypatch):
    p,e,prep,audit=setup; monkeypatch.delenv('AUTOLAB_TEST_MISSING',raising=False)
    prep.registry=CapabilityRegistry([Capability(capability_id='filesystem_access',status='AVAILABLE',credential_requirement='AUTOLAB_TEST_MISSING')])
    result=run(prep.prepare(p.project_id)); assert result.status=='NEEDS_USER_INPUT' and 'AUTOLAB_TEST_MISSING' in result.summary


@pytest.mark.parametrize('change',['fingerprint','project','version','requirements','extra_science'])
def test_agent_cannot_change_science_or_assigned_contract(setup,change):
    p,e,prep,audit=setup
    def mutate(plan):
        if change=='requirements': return plan.model_copy(update={'resource_requirements':[]})
        if change=='extra_science': return {**plan.model_dump(),'primary_metric':'changed'}
        key={'fingerprint':'spec_fingerprint','project':'project_id','version':'experiment_version'}[change]
        return plan.model_copy(update={key:2 if key=='experiment_version' else 'wrong'})
    prep.agent=Preparer(mutate=mutate)
    with pytest.raises(PreparationError): run(prep.prepare(p.project_id))
    assert prep.ledger.get_experiment(e.experiment_id)==e and not prep.ledger.list_resources(p.project_id)


@pytest.mark.parametrize('changes,expected',[({'blocks':['Missing valid matched condition']},'BLOCK'),({'changes':['Would change primary metric']},'BLOCK'),({'risks':['New paid external data exposure']},'NEEDS_REAPPROVAL')])
def test_material_science_or_risk_escalation(setup,changes,expected):
    p,e,prep,audit=setup; prep.agent=Preparer(**changes)
    result=run(prep.prepare(p.project_id)); assert result.status==expected
    assert not prep.ledger.list_resources(p.project_id)


@pytest.mark.parametrize('cost,duration',[(6,1),(1,31)])
def test_cost_runtime_caps_require_reapproval(setup,cost,duration):
    p,e,prep,audit=setup; prep.agent=Preparer([requirement(estimated_cost_usd=cost,estimated_runtime_minutes=duration)])
    assert run(prep.prepare(p.project_id)).status=='NEEDS_REAPPROVAL'; assert not prep.ledger.list_resources(p.project_id)


def test_resource_generation_provenance_checksums_manifest_and_restart(setup):
    p,e,prep,audit=setup; result,snap=prepared(setup); m=current_manifest(snap); r=snap.resources[0]
    assert checksum(r.path_or_uri)==r.checksum and not manifest_errors(snap,m)
    assert r.metadata['seed']==7 and r.metadata['generator']=='declarative-json-v1'
    assert r.metadata['specification'] and r.metadata['model_metadata']=={} and r.metadata['generation_parameters']
    assert m.resources[0].resource_id==r.resource_id and len(m.model_dump_json())<15000
    assert 'data' not in m.model_dump() and m.unresolved_warnings
    assert ResourceManifest.model_validate_json(Path(m.manifest_path).read_text())==m
    with ResearchLedger(prep.ledger.database.path) as reopened:
        assert current_manifest(load_snapshot(reopened,p.project_id))==m


def test_duplicate_preparation_returns_manifest_without_reexecution(setup):
    p,e,prep,audit=setup; first,snap=prepared(setup); second=run(prep.prepare(p.project_id))
    assert first.resource_ids==second.resource_ids and prep.agent.calls==1 and len(prep.ledger.list_resources(p.project_id))==1


def test_existing_shared_resource_referenced_once(setup,tmp_path):
    p,e,prep,audit=setup; path=tmp_path/'shared.json'; path.write_text(json.dumps(requirement().parameters['data']))
    prep.catalog=[{'path':str(path),'source':'Operator supplied shared fixture'}]
    prep.agent=Preparer([requirement(handler='local',acquisition_mode='EXISTING',parameters={'path':str(path)},source='Operator supplied shared fixture')])
    result=run(prep.prepare(p.project_id)); r=prep.ledger.list_resources(p.project_id)[0]
    assert Path(r.path_or_uri).parent==tmp_path/'data/shared' and r.metadata['source_path']==str(path)
    assert r.checksum==checksum(path) and len(list((tmp_path/'data/shared').iterdir()))==1


def test_transform_references_parent_and_preserves_seed(setup):
    p,e,prep,audit=setup
    derived=requirement(requirement_id='derived',handler='transform',acquisition_mode='DERIVE',dependencies=['inputs'],
        parameters={'parent_requirement':'inputs','operation':'split','seed':12,'group_field':'id','split_field':'split','train_fraction':0.5})
    prep.agent=Preparer([requirement(),derived]); run(prep.prepare(p.project_id)); resources=prep.ledger.list_resources(p.project_id)
    assert resources[1].metadata['parent_ids']==[resources[0].resource_id] and resources[1].metadata['seed']==12
    assert resources[1].metadata['parent_checksums']=={resources[0].resource_id:resources[0].checksum}


@pytest.mark.parametrize('defect,check',[('missing','file_exists'),('schema','required_fields'),('types','field_types'),('duplicate','duplicates'),('count','sample_count'),('condition','condition_coverage'),('json','readable'),('hash','sha256'),('provenance','provenance')])
def test_deterministic_resource_failures(setup,defect,check):
    p,e,prep,audit=setup
    if defect not in ('missing','hash','provenance'):
        r=requirement(); rows=r.parameters['data']
        if defect=='schema': rows[0].pop('text')
        elif defect=='types': rows[0]['id']=0
        elif defect=='duplicate': rows[1]=rows[0]
        elif defect=='count': rows.pop()
        elif defect=='condition':
            for row in rows: row['condition']='A'
        elif defect=='json': pass
        prep.agent=Preparer([r])
    _,snap=prepared(setup); m=current_manifest(snap)
    if defect=='missing': Path(snap.resources[0].path_or_uri).unlink()
    elif defect=='hash': Path(snap.resources[0].path_or_uri).write_text('[]')
    elif defect=='json': Path(snap.resources[0].path_or_uri).write_text('not json')
    elif defect=='provenance': snap=snap.model_copy(update={'resources':[snap.resources[0].model_copy(update={'metadata':{}})]})
    evidence=ValidatorRegistry().validate(snap,m)
    assert any(f['check']==check and not f['passed'] for f in evidence.findings)


def test_split_overlap_detected(setup):
    p,e,prep,audit=setup; r=requirement(); rows=r.parameters['data']
    for row in rows: row['group']='same'; row['split']='train' if row['condition']=='A' else 'test'
    r=r.model_copy(update={'criteria':r.criteria.model_copy(update={'split_field':'split','split_group_fields':['group']})})
    prep.agent=Preparer([r]); _,snap=prepared(setup); ev=ValidatorRegistry().validate(snap,current_manifest(snap))
    assert any(f['check']=='split_independence' and not f['passed'] for f in ev.findings)


def test_technically_valid_synthetic_target_shortcut_rejected(setup):
    p,e,prep,audit=setup; r=requirement()
    for row in r.parameters['data']: row.update(label=row['condition'],shortcut=row['condition'])
    r=r.model_copy(update={'criteria':r.criteria.model_copy(update={'label_field':'label','input_fields':['text','shortcut']})})
    prep.agent=Preparer([r]); run(prep.prepare(p.project_id)); report=run(audit.audit(p.project_id))
    deterministic=report.metadata['deterministic_findings']
    assert all(f['passed'] for f in deterministic if f['gate']=='technical')
    assert any(f['check']=='target_leakage' and not f['passed'] for f in deterministic)
    assert report.verdict=='REPAIR' and not report.scientific_readiness and not readiness_passes(load_snapshot(prep.ledger,p.project_id))


@pytest.mark.parametrize('prediction_visible_target',[False,True])
def test_perfect_numeric_control_is_not_itself_target_access(prediction_visible_target):
    from types import SimpleNamespace
    from autolab.preparation.models import AcceptanceCriteria
    from autolab.readiness.validators.dataset import DatasetValidator
    from autolab.readiness.validators.base import ValidationEvidence
    rows=[{'sample_id':'a','prediction':.7,'target':.7},
          {'sample_id':'b','prediction':1.2,'target':1.3}]
    c=AcceptanceCriteria(required_fields=['sample_id','prediction','target'],min_samples=2,
        scientific=['Scorer-only target access'],technical=['Complete numeric rows'],provenance=['Explicit test fixture'],
        label_field='target',input_fields=['prediction','target'] if prediction_visible_target else ['prediction'])
    evidence=ValidationEvidence()
    DatasetValidator().validate(SimpleNamespace(resource_id='RES_TEST'),c,evidence,rows)
    finding=next(f for f in evidence.findings if f['check']=='target_leakage')
    assert finding['passed'] is (not prediction_visible_target)
    assert evidence.summaries[0]['samples']==rows
    assert evidence.summaries[0]['suspicious_samples']==[rows[0]]


@pytest.mark.parametrize('verdict',['PASS','REPAIR','BLOCK'])
def test_independent_four_gate_verdicts_persist(setup,verdict):
    p,e,prep,audit=setup; _,snap=prepared(setup); audit.agent=Auditor(verdict)
    report=run(audit.audit(p.project_id)); restored=prep.ledger.get(s.ReadinessReport,report.readiness_id)
    assert restored==report and report.verdict==verdict and report.metadata['semantic_findings'] and report.metadata['deterministic_findings']
    assert report.metadata['resource_pins']==[pin.model_dump(mode='json') for pin in current_manifest(snap).resources]
    assert not prep.ledger.list_records(s.ImplementationRecord,p.project_id) and not prep.ledger.list_records(s.ExperimentRun,p.project_id)


@pytest.mark.parametrize('bad',['id','version','foreign_resource','malformed','no_semantic','inconsistent_pass'])
def test_malformed_or_fabricated_auditor_output_bounded(setup,bad):
    p,e,prep,audit=setup; prepared(setup)
    def mutate(r):
        if bad=='id': return r.model_copy(update={'experiment_id':'EXP_FOREIGN'})
        if bad=='version': return r.model_copy(update={'experiment_version':2})
        if bad=='foreign_resource': return r.model_copy(update={'metadata':{'semantic_findings':[{'resource_ids':['RES_FAKE']} ]}})
        if bad=='no_semantic': return r.model_copy(update={'metadata':{}})
        if bad=='inconsistent_pass': return r.model_copy(update={'scientific_readiness':False})
        return {'verdict':'BAD'}
    audit.agent=Auditor(mutate=mutate)
    with pytest.raises(PreparationError): run(audit.audit(p.project_id))
    assert audit.agent.calls==1 and not prep.ledger.list_records(s.ReadinessReport,p.project_id)


@pytest.mark.parametrize('disposition',['ACCEPT','REBUT','CLARIFY'])
def test_repair_classification_and_history_preserved(setup,disposition):
    p,e,prep,audit=setup; prep.agent=Preparer(responses=disposition); audit.agent=Auditor(sequence=['REPAIR','PASS'])
    result=run(prep.run(p.project_id,audit)); snap=load_snapshot(prep.ledger,p.project_id); resources=snap.resources
    assert result.status=='PASS' and result.repair_attempts==1
    if disposition=='ACCEPT':
        assert len(resources)==2 and resources[1].version=='2' and resources[1].metadata['previous_resource_id']==resources[0].resource_id
    else: assert len(resources)==1
    assert Path(resources[0].path_or_uri).exists() and current_plan(snap).issue_responses[0].disposition==disposition
    assert len(snap.readiness)==2


def test_bounded_repair_exhaustion_returns_planner(setup):
    p,e,prep,audit=setup; audit.agent=Auditor('REPAIR')
    result=run(prep.run(p.project_id,audit)); snap=load_snapshot(prep.ledger,p.project_id)
    assert result.status=='BLOCK' and result.repair_attempts==2 and prep.agent.calls==3 and audit.agent.calls==3
    assert snap.readiness[-1].verdict=='BLOCK' and derive_control_state(snap).value=='ADAPTIVE_DECISION'
    assert not readiness_passes(snap)


def test_block_returns_planner_no_fake_implementation(setup):
    p,e,prep,audit=setup; audit.agent=Auditor('BLOCK'); result=run(prep.run(p.project_id,audit))
    snap=load_snapshot(prep.ledger,p.project_id)
    assert result.status=='BLOCK' and prep.agent.calls==1 and derive_control_state(snap).value=='ADAPTIVE_DECISION'
    assert not DecisionValidator().validate(decision(snap),snap).valid
    assert DecisionValidator().validate(decision(snap,'GATHER_EVIDENCE','evidence'),snap).valid


@pytest.mark.parametrize('change',['content','new_resource','spec','manifest','pins','new_audit_failed'])
def test_stale_readiness_never_authorizes_implementation(setup,change):
    p,e,prep,audit=setup; run(prep.run(p.project_id,audit)); snap=load_snapshot(prep.ledger,p.project_id)
    assert readiness_passes(snap)
    if change=='content': Path(snap.resources[0].path_or_uri).write_text('[]')
    elif change=='new_resource': prep.ledger.add_resource(snap.resources[0].model_copy(update={'resource_id':prep.ledger.next_id('RES'),'version':'2','created_at':s.utc_now()}))
    elif change=='spec': prep.ledger.add_experiment_spec(e.model_copy(update={'version':2}))
    elif change=='manifest': Path(current_manifest(snap).manifest_path).write_text('{}')
    elif change=='new_audit_failed':
        audit.agent=Auditor(mutate=lambda r: {'bad':True})
        with pytest.raises(PreparationError): run(audit.audit(p.project_id))
    else:
        report=snap.readiness[-1].model_copy(update={'metadata':{**snap.readiness[-1].metadata,'resource_pins':[]}})
        snap=snap.model_copy(update={'readiness':[report]})
    if change!='pins': snap=load_snapshot(prep.ledger,p.project_id)
    assert not readiness_passes(snap) and not DecisionValidator().validate(decision(snap),snap).valid


def test_implementation_boundary_before_after_pass_and_adaptive_planner(setup):
    p,e,prep,audit=setup; _,snap=prepared(setup)
    assert not DecisionValidator().validate(decision(snap),snap).valid
    run(audit.audit(p.project_id)); snap=load_snapshot(prep.ledger,p.project_id)
    assert DecisionValidator().validate(decision(snap),snap).valid
    context=ContextBuilder().build(snap)
    assert context.current_records['readiness']['current_pass'] and context.current_records['resource_manifest']
    class Planner:
        async def propose(self, context, decision_id, feedback=None):
            return decision(snap,'GATHER_EVIDENCE','evidence').model_copy(update={'decision_id':decision_id}).model_dump_json()
    route=run(Orchestrator(prep.ledger,Planner()).decide(p.project_id))
    assert route.action=='GATHER_EVIDENCE' and not prep.ledger.list_records(s.ImplementationRecord,p.project_id)


def test_preparation_only_scope_does_not_expand_to_implementation(ledger,tmp_path):
    p,e,reg=seed(ledger,implementation_scope=False); prep=PreparationService(ledger,Preparer(),registry=reg,root=tmp_path)
    run(prep.run(p.project_id,ReadinessService(ledger,Auditor())))
    snap=load_snapshot(ledger,p.project_id)
    assert readiness_passes(snap) and not DecisionValidator().validate(decision(snap),snap).valid


def test_orchestrator_preparation_dispatch_returns_without_phase9(setup):
    p,e,prep,audit=setup
    class Planner:
        async def propose(self, context, decision_id, feedback=None):
            return s.NextDecision(decision_id=decision_id,project_id=p.project_id,action='PREPARE_RESOURCES',target_agent='preparation',reason='Prepare approved fixture',remaining_budget_usd=100).model_dump_json()
    orch=Orchestrator(prep.ledger,Planner()); route=run(orch.decide(p.project_id)); result=run(orch.execute_preparation(route,prep,audit))
    assert result.status=='PASS' and prep.agent.calls==1 and audit.agent.calls==1
    with pytest.raises(IllegalDecisionError): run(orch.execute_preparation(route,prep,audit))
    assert not prep.ledger.list_records(s.ImplementationRecord,p.project_id) and not prep.ledger.list_records(s.ExperimentRun,p.project_id)


@pytest.mark.parametrize('parameters',[{'shell':'touch bad'},{'data':[],'specification':'test','code':'eval(1)'},{'data':[],'specification':'test','pip_install':'evil'}])
def test_arbitrary_executable_parameters_never_execute(setup,parameters):
    p,e,prep,audit=setup; prep.agent=Preparer([requirement(parameters=parameters)])
    with pytest.raises(PreparationError): run(prep.prepare(p.project_id))
    assert not prep.ledger.list_resources(p.project_id)


@pytest.mark.parametrize('suffix',['.py','.sh','.pkl','.pickle','.exe'])
def test_executable_local_resources_not_loaded_or_run(setup,tmp_path,suffix):
    p,e,prep,audit=setup; path=tmp_path/('untrusted'+suffix); path.write_text('raise RuntimeError("not executed")')
    prep.agent=Preparer([requirement(handler='local',acquisition_mode='EXISTING',parameters={'path':str(path)})])
    with pytest.raises(PreparationError): run(prep.prepare(p.project_id))
    assert not prep.ledger.list_resources(p.project_id)


def test_credentials_never_persist(setup,monkeypatch):
    p,e,prep,audit=setup; secret='private-phase8-test-key-value'; monkeypatch.setenv('OPENAI_API_KEY',secret)
    prep.agent=Preparer([requirement(parameters={'data':{'secret':secret},'specification':'fixture'})])
    with pytest.raises(PreparationError) as error: run(prep.prepare(p.project_id))
    assert secret not in str(error.value) and secret not in ''.join(ev.model_dump_json() for ev in prep.ledger.list_events(p.project_id))


def test_failed_batch_rolls_back_resources_and_generated_artifacts(setup):
    p,e,prep,audit=setup; prep.agent=Preparer([requirement(),requirement(requirement_id='bad',handler='local',acquisition_mode='EXISTING',parameters={'path':'/missing.json'})])
    with pytest.raises(PreparationError): run(prep.prepare(p.project_id))
    assert not prep.ledger.list_resources(p.project_id) and not list(prep.root.rglob('RES_*.json'))
    assert prep.ledger.get_experiment(e.experiment_id)==e

@pytest.mark.parametrize('url',['https://public.example/resource.py','https://public.example/data.json?token=secret','http://public.example/data.json','https://user:password@public.example/data.json','https://unapproved.example/data.json'])
def test_downloads_require_exact_public_data_allowlist(setup,url):
    p,e,prep,audit=setup; prep.allowed_downloads={'https://public.example/data.json'}
    prep.agent=Preparer([requirement(handler='download',acquisition_mode='DOWNLOAD',parameters={'url':url,'sha256':'0'*64})])
    with pytest.raises(PreparationError): run(prep.prepare(p.project_id))
    assert not prep.ledger.list_resources(p.project_id)


@pytest.mark.parametrize('corrupt',[False,True])
def test_pinned_small_download_is_data_only(setup,monkeypatch,corrupt):
    import hashlib
    from autolab.preparation.handlers import download
    p,e,prep,audit=setup; url='https://public.example/data.json'; content=json.dumps(requirement().parameters['data']).encode()
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,bound): return content
    class Opener:
        def open(self,req,timeout): return Response()
    monkeypatch.setattr(download,'build_opener',lambda *args: Opener())
    prep.allowed_downloads={url}
    prep.agent=Preparer([requirement(handler='download',acquisition_mode='DOWNLOAD',parameters={'url':url,
        'sha256':'0'*64 if corrupt else hashlib.sha256(content).hexdigest(),'license':'Fixture license'},source='Public fixture')])
    if corrupt:
        with pytest.raises(PreparationError): run(prep.prepare(p.project_id))
        assert not prep.ledger.list_resources(p.project_id)
    else:
        result=run(prep.prepare(p.project_id)); record=prep.ledger.list_resources(p.project_id)[0]
        assert record.metadata['license']=='Fixture license' and record.metadata['download_execution'].startswith('none')
        assert result.status=='PREPARED'


def test_named_custom_credentials_rejected_before_plan_persistence(setup,monkeypatch):
    p,e,prep,audit=setup; secret='custom-vendor-test-secret'; monkeypatch.setenv('CUSTOM_VENDOR_KEY',secret)
    prep.registry=CapabilityRegistry([Capability(capability_id='filesystem_access',status='AVAILABLE',credential_requirement='CUSTOM_VENDOR_KEY')])
    prep.agent=Preparer([requirement(parameters={'data':{'value':secret},'specification':'public fixture'})])
    with pytest.raises(PreparationError): run(prep.prepare(p.project_id))
    assert secret not in ''.join(e.model_dump_json() for e in prep.ledger.list_events(p.project_id))


def test_new_paid_capability_requires_reapproval_even_if_available(setup):
    p,e,prep,audit=setup
    prep.registry.register(Capability(capability_id='new_paid_provider',status='AVAILABLE',cost_driver='Unassessed paid inference'))
    prep.agent=Preparer([requirement(required_capabilities=['filesystem_access','new_paid_provider'])])
    assert run(prep.prepare(p.project_id)).status=='NEEDS_REAPPROVAL'
    from autolab.orchestration.state_machine import approval_for
    assert approval_for(load_snapshot(prep.ledger,p.project_id),s.PlannerAction.PREPARE_RESOURCES) is None


def test_independent_validator_extension_point(setup):
    p,e,prep,audit=setup
    class Extension:
        def validate(self,r,c,evidence,data): evidence.add(r,'extension_check',False,'Independent adapter found unsupported artifact','quality')
    audit.validators.register(Extension()); run(prep.prepare(p.project_id)); report=run(audit.audit(p.project_id))
    assert report.verdict=='REPAIR' and not report.quality_readiness


def test_shared_parent_and_declared_split_are_reproducible(setup):
    p,e,prep,audit=setup
    derived=requirement(requirement_id='derived',handler='transform',acquisition_mode='DERIVE',dependencies=['inputs'],
        parameters={'parent_requirement':'inputs','operation':'split','seed':91,'group_field':'id','split_field':'split','train_fraction':0.5})
    prep.agent=Preparer([requirement(),derived]); result=run(prep.prepare(p.project_id))
    resources=prep.ledger.list_resources(p.project_id)
    data=json.loads(Path(resources[1].path_or_uri).read_text())
    from autolab.preparation.handlers.transform import TransformHandler
    again=TransformHandler().prepare(derived,{'allowed_roots':prep.allowed_roots,'resources':{'inputs':resources[0]}})
    assert json.loads(again.content)==data and {r['split'] for r in data}=={'train','test'}


def test_repair_cannot_relax_criteria(setup):
    p,e,prep,audit=setup; prepared(setup); audit.agent=Auditor('REPAIR'); report=run(audit.audit(p.project_id))
    plan=current_plan(load_snapshot(prep.ledger,p.project_id))
    def relax(new):
        req=new.resource_requirements[0]
        req=req.model_copy(update={'criteria':req.criteria.model_copy(update={'min_samples':1})})
        return new.model_copy(update={'resource_requirements':[req]})
    prep.agent=Preparer(mutate=relax)
    with pytest.raises(PreparationError): run(prep.prepare(p.project_id,previous=plan,issues=report.metadata['issues']))
    assert len(prep.ledger.list_resources(p.project_id))==1


def test_repair_needs_current_persisted_auditor_report(setup):
    p,e,prep,audit=setup; prepared(setup); plan=current_plan(load_snapshot(prep.ledger,p.project_id))
    with pytest.raises(PreparationError,match='persisted current independent'): run(prep.prepare(p.project_id,previous=plan,issues=[{'problem':'Untrusted request'}]))
    assert prep.agent.calls==1


def test_repair_changes_only_accepted_resources(setup):
    p,e,prep,audit=setup; prep.agent=Preparer([requirement(),requirement(requirement_id='other')]); run(prep.prepare(p.project_id))
    old=prep.ledger.list_resources(p.project_id)
    def issue(r):
        return r.model_copy(update={'metadata':{**r.metadata,'issues':[{'problem':'Repair first resource','resource_ids':[old[0].resource_id]}]}})
    audit.agent=Auditor('REPAIR',mutate=issue); report=run(audit.audit(p.project_id)); plan=current_plan(load_snapshot(prep.ledger,p.project_id))
    result=run(prep.prepare(p.project_id,previous=plan,issues=report.metadata['issues']))
    resources=prep.ledger.list_resources(p.project_id)
    assert len(resources)==3 and result.resource_ids[1]==old[1].resource_id and old[0].resource_id not in result.resource_ids


def test_readiness_rejects_wrong_resource_versions(setup):
    p,e,prep,audit=setup; prepared(setup)
    def wrong(r):
        snap=load_snapshot(prep.ledger,p.project_id); pins=[p.model_dump(mode='json') for p in current_manifest(snap).resources]
        pins[0]['version']='999'
        return r.model_copy(update={'metadata':{**r.metadata,'resource_pins':pins}})
    audit.agent=Auditor(mutate=wrong)
    with pytest.raises(PreparationError): run(audit.audit(p.project_id))
    assert not readiness_passes(load_snapshot(prep.ledger,p.project_id))


def test_agent_cannot_grant_readiness_without_independent_event(setup):
    p,e,prep,audit=setup; run(prep.run(p.project_id,audit)); snap=load_snapshot(prep.ledger,p.project_id)
    snap=snap.model_copy(update={'events':[e for e in snap.events if e.event_type!='READINESS_PASSED']})
    assert not readiness_passes(snap)


def test_semantic_sampling_is_bounded(setup):
    p,e,prep,audit=setup; req=requirement()
    rows=[{'id':str(i),'text':f'Unique task {i}','condition':'A' if i%2 else 'B'} for i in range(2000)]
    prep.agent=Preparer([req.model_copy(update={'parameters':{**req.parameters,'data':rows}})])
    captured={}
    class Capture(Auditor):
        async def audit(self,context,assignment):
            captured.update(context); return await super().audit(context,assignment)
    audit.agent=Capture(); run(prep.run(p.project_id,audit))
    assert captured['resource_summaries'][0]['count']==2000
    assert len(captured['resource_summaries'][0]['samples'])<=12 and len(json.dumps(captured))<30000
    assert 'Unique task 1000' not in json.dumps(captured)


def test_existing_resource_cannot_read_uncatalogued_project_json(setup,tmp_path):
    p,e,prep,audit=setup; path=tmp_path/'private.json'; path.write_text('{"internal":"not authorized scientific input"}')
    prep.agent=Preparer([requirement(handler='local',acquisition_mode='EXISTING',parameters={'path':str(path)})])
    with pytest.raises(PreparationError): run(prep.prepare(p.project_id))
    assert not prep.ledger.list_resources(p.project_id)


def test_custom_secret_in_catalogued_artifact_is_not_persisted(setup,tmp_path,monkeypatch):
    p,e,prep,audit=setup; secret='secret-value-from-source-catalog'; monkeypatch.setenv('CUSTOM_VENDOR_KEY',secret)
    prep.registry=CapabilityRegistry([Capability(capability_id='filesystem_access',status='AVAILABLE',credential_requirement='CUSTOM_VENDOR_KEY')])
    path=tmp_path/'source.json'; path.write_text(json.dumps({'value':secret})); prep.catalog=[{'path':str(path)}]
    prep.agent=Preparer([requirement(handler='local',acquisition_mode='EXISTING',parameters={'path':str(path)})])
    with pytest.raises(PreparationError): run(prep.prepare(p.project_id))
    assert not prep.ledger.list_resources(p.project_id)
    assert secret not in ''.join(ev.model_dump_json() for ev in prep.ledger.list_events(p.project_id))


def test_blocked_plan_can_preserve_unresolved_path_without_dispatch(setup):
    p,e,prep,audit=setup; prep.agent=Preparer([requirement(handler='local',acquisition_mode='EXISTING',parameters={})],blocks=['No approved catalog path exists'])
    result=run(prep.prepare(p.project_id))
    assert result.status=='BLOCK' and current_plan(load_snapshot(prep.ledger,p.project_id)).resource_requirements[0].parameters=={}
    assert not prep.ledger.list_resources(p.project_id)


def test_source_change_cannot_overwrite_immutable_shared_artifact(setup,tmp_path):
    p,e,prep,audit=setup; path=tmp_path/'source.json'; path.write_text(json.dumps(requirement().parameters['data']))
    prep.catalog=[{'path':str(path)}]; prep.agent=Preparer([requirement(handler='local',acquisition_mode='EXISTING',parameters={'path':str(path)})])
    run(prep.prepare(p.project_id)); record=prep.ledger.list_resources(p.project_id)[0]; original=Path(record.path_or_uri).read_bytes()
    path.write_text('[]')
    assert Path(record.path_or_uri).read_bytes()==original and checksum(record.path_or_uri)==record.checksum
    run(audit.audit(p.project_id)); assert readiness_passes(load_snapshot(prep.ledger,p.project_id))


def test_unsafe_experiment_id_cannot_escape_resource_root(ledger,tmp_path):
    p,e,reg=seed(ledger)
    # Canonical IDs are strings, but storage must enforce a safe single component.
    from autolab.preparation.models import ResourcePreparationPlan
    plan=ResourcePreparationPlan(plan_id='PPLAN_UNSAFE',project_id=p.project_id,experiment_id='../outside',
        experiment_version=1,spec_fingerprint='fixture',resource_requirements=[requirement()])
    service=PreparationService(ledger,Preparer(),registry=reg,root=tmp_path)
    unsafe=e.model_copy(update={'experiment_id':'../outside'})
    with pytest.raises(PreparationError,match='safe artifact'): service._create(plan,unsafe,None,[])
    assert not (tmp_path/'outside').exists()


def test_missing_credential_can_resume_same_acceptance_plan_after_configuration(setup,monkeypatch):
    p,e,prep,audit=setup; monkeypatch.delenv('CUSTOM_VENDOR_KEY',raising=False)
    prep.registry=CapabilityRegistry([Capability(capability_id='filesystem_access',status='AVAILABLE',credential_requirement='CUSTOM_VENDOR_KEY')])
    blocked=run(prep.prepare(p.project_id)); assert blocked.status=='NEEDS_USER_INPUT'
    before=current_plan(load_snapshot(prep.ledger,p.project_id)); monkeypatch.setenv('CUSTOM_VENDOR_KEY','private-test-only-credential')
    result=run(prep.prepare(p.project_id)); assert result.status=='PREPARED' and prep.agent.calls==1
    assert current_plan(load_snapshot(prep.ledger,p.project_id))==before
    assert 'private-test-only-credential' not in ''.join(r.model_dump_json() for r in prep.ledger.list_resources(p.project_id))


def test_changed_risk_requires_new_assessment_packet_and_explicit_human_then_resume(setup):
    from autolab.feasibility.approval import ApprovalService
    from autolab.feasibility.models import FeasibilityInputs,ResourceAccess,CostInput,EstimateRange
    from autolab.feasibility.persistence import current_packet
    from autolab.feasibility.service import FeasibilityService,FeasibilityError
    p,e,prep,audit=setup; prep.agent=Preparer(risks=['New declared fixture risk'],requirements=[requirement(estimated_cost_usd=6)])
    blocked=run(prep.prepare(p.project_id)); assert blocked.status=='NEEDS_REAPPROVAL'
    approval=ApprovalService(prep.ledger,allow_test_human=True)
    old=current_packet(load_snapshot(prep.ledger,p.project_id))
    with pytest.raises(FeasibilityError,match='refresh feasibility'): approval.request_approval(p.project_id,e.experiment_id)
    with pytest.raises(FeasibilityError,match='refreshed feasibility'): approval.record_human_decision(p.project_id,e.experiment_id,1,'APPROVE',packet_id=old.packet_id,actor='test-human')
    inputs=FeasibilityInputs(resource_access=[ResourceAccess(requirement='Task inputs',status='AVAILABLE')],
        costs=[CostInput(category='new explicit fixture estimate',unit_price_usd=1,units=EstimateRange(maximum=8))],
        runtime_minutes=EstimateRange(maximum=30),compute_requirements=['Local CPU fixture'],
        storage_gb=EstimateRange(maximum=.01),execution_risks=['New declared fixture risk'])
    FeasibilityService(prep.ledger,prep.registry).assess(p.project_id,e.experiment_id,inputs)
    packet=approval.request_approval(p.project_id,e.experiment_id)
    approval.record_human_decision(p.project_id,e.experiment_id,1,'APPROVE',packet_id=packet.packet_id,actor='test-human',
        max_cost_usd=10,max_runtime_minutes=30,approved_actions=['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT'])
    result=run(prep.prepare(p.project_id)); assert result.status=='PREPARED' and prep.agent.calls==1
    assert prep.ledger.get_experiment(e.experiment_id)==e


def test_configuration_object_schema_validated_without_treating_it_as_dataset(setup):
    p,e,prep,audit=setup; r=requirement(resource_type='configuration',parameters={'data':{'setting':8},'specification':'Frozen fixture setting'})
    c=r.criteria.model_copy(update={'required_fields':['setting'],'field_types':{'setting':'integer'},'min_samples':1,
        'unique_fields':[],'condition_field':None,'required_conditions':[]})
    prep.agent=Preparer([r.model_copy(update={'criteria':c})]); prepared(setup)
    report=run(audit.audit(p.project_id))
    assert report.verdict=='PASS'


def test_hidden_reference_column_is_not_a_leak_when_excluded_from_inputs(setup):
    p,e,prep,audit=setup; r=requirement()
    for row in r.parameters['data']: row['reference']='hidden-'+row['id']
    c=r.criteria.model_copy(update={'label_field':'reference','input_fields':['text'],'forbidden_input_fields':['reference']})
    prep.agent=Preparer([r.model_copy(update={'criteria':c})]); prepared(setup)
    report=run(audit.audit(p.project_id))
    assert report.verdict=='PASS' and report.scientific_readiness
