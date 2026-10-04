"""Offline Phase 10 execution, result integrity and scientific boundary tests."""
import asyncio
import json
import math
from pathlib import Path
import pytest
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.feasibility.persistence import spec_fingerprint
from autolab.implementation.service import ImplementationService
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import derive_control_state, current_implementation
from autolab.orchestration.models import ControlStage as C
from autolab.orchestration.budget import calculate_budget
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.orchestrator import Orchestrator, IllegalDecisionError
from autolab.runtime.service import ExperimentRuntime
from autolab.runtime.models import RuntimeErrorRecord
from autolab.runtime.persistence import valid_result, active_run
from autolab.runtime.adapters import ScalarFixtureAdapter
from autolab.runtime_smoke_helpers import PROJECT, authorize_execution, verify_real_run_blocked
from autolab.implementation_smoke_helpers import seed_fixture
from phase9_helpers import Implementer, Auditor, run


def decision(snapshot, action='RUN_EXPERIMENT', target='experiment_runner', identifier='DEC_RUNTIME'):
    return s.NextDecision(decision_id=identifier,project_id=snapshot.charter.project_id,action=action,target_agent=target,
        reason='Explicit offline test decision',remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd)


@pytest.fixture
def ready_runtime(ledger,tmp_path):
    project,spec,contract=run(seed_fixture(ledger,tmp_path,project_id=PROJECT,experiment_id='EXP_PHASE10',execution_fixture=True))
    def rebind(files): return {n:v.replace('EXP_PHASE9','EXP_PHASE10') for n,v in files.items()}
    service=ImplementationService(ledger,Implementer(mutate_source=rebind),Auditor(),root=tmp_path,contracts={spec_fingerprint(spec):contract})
    result=run(service.run(PROJECT)); assert result.status=='READY'
    authorize_execution(ledger,current_implementation(load_snapshot(ledger,PROJECT)))
    runtime=ExperimentRuntime(ledger,root=tmp_path,adapters={spec_fingerprint(spec):ScalarFixtureAdapter(spec_fingerprint(spec))})
    return runtime,service,spec


def snapshot(fixture): return load_snapshot(fixture[0].ledger,PROJECT)


def replace_implementation(fixture,transform):
    runtime,service,spec=fixture
    def mutate(files):
        files={n:v.replace('EXP_PHASE9','EXP_PHASE10') for n,v in files.items()}
        files['experiment.py']=transform(files['experiment.py'])
        return files
    service.implementer=Implementer(mutate_source=mutate)
    previous=current_implementation(snapshot(fixture))
    service.auditor=Auditor(sequence=['REVISE'])
    review=run(service.audit(PROJECT))
    record=run(service.implement(PROJECT,previous=previous,review=review))
    service.auditor=Auditor()
    assert run(service.audit(PROJECT)).verdict=='PASS'
    authorize_execution(service.ledger,current_implementation(snapshot(fixture)))


def assert_no_analysis(snap):
    assert not snap.analyses
    assert not any(e.actor in ('analyst','analysis') for e in snap.events)


def test_runtime_executes_actual_rules_and_persists_run_scoped_metrics(ready_runtime):
    runtime,service,spec=ready_runtime
    assert not DecisionValidator().validate(decision(snapshot(ready_runtime),'ANALYZE_RESULT','analyst'),snapshot(ready_runtime)).valid
    record=run(runtime.run(PROJECT)); snap=snapshot(ready_runtime)
    assert record.status==s.RunStatus.COMPLETED and valid_result(snap,record)
    assert record.run_id=='RUN_0001' and record.random_seed==19 and record.experiment_version==1
    cfg=record.environment_metadata['config']; impl=current_implementation(snap)
    assert cfg['implementation_hash']==impl.code_version and cfg['manifest_id']=='MANIFEST_0001'
    assert cfg['dependency_pins']['resource_pins'] and cfg['retries']==0
    assert 0<record.environment_metadata['duration_seconds']<10 and record.completed_at>=record.started_at
    assert record.environment_metadata['python_version'] and record.environment_metadata['exit_status']==0
    raw=[json.loads(line) for line in Path(record.output_manifest['artifacts']['raw_outputs.jsonl']['path']).read_text().splitlines()]
    assert len(raw)==8 and all(o['run_id']==record.run_id and o['experiment_id']==spec.experiment_id for o in raw)
    assert {o['observation']['sample_id'] for o in raw}=={'toy-0','toy-1','toy-2','toy-3'}
    assert {o['observation']['condition'] for o in raw}=={'baseline','clipped'}
    values={m.metadata['condition']:m.metric_value for m in snap.metrics}
    assert math.isclose(values['baseline'],.175) and math.isclose(values['clipped'],.075)
    for metric in snap.metrics:
        group=[o['observation'] for o in raw if o['observation']['condition']==metric.metadata['condition']]
        independently=sum(abs(o['outputs']['prediction']-o['outputs']['target']) for o in group)/4
        assert math.isclose(metric.metric_value,independently) and metric.metadata['denominator']==4
        assert metric.run_id==record.run_id and metric.metadata['independent_recomputation']
    assert {m.metric_name for m in snap.metrics}=={spec.primary_metric}
    assert not any('hypothesis_assessment' in o or 'interpretation' in o for o in raw)
    assert record.cost_usd is None and snap.costs[-1].actual_usd is None
    assert snap.costs[-1].metadata['actual_known'] is False
    assert snap.costs[-1].cost_id in calculate_budget(snap).unknown_actual_cost_ids
    assert record.environment_metadata['usage']['calls']==8
    assert derive_control_state(snap)==C.ANALYSIS
    assert DecisionValidator().validate(decision(snap,'ANALYZE_RESULT','analyst'),snap).valid
    ctx=ContextBuilder().build(snap)
    assert ctx.current_records['run']['integrity_valid'] and 'observations' not in ctx.current_records['run']
    assert_no_analysis(snap)


def test_repeated_runs_preserve_history_and_reproduce_measurements(ready_runtime):
    runtime,*_=ready_runtime; a=run(runtime.run(PROJECT)); b=run(runtime.run(PROJECT)); snap=snapshot(ready_runtime)
    assert a.run_id!=b.run_id and len(snap.runs)==2
    def raw(record):
        return [json.loads(l)['observation'] for l in Path(record.output_manifest['artifacts']['raw_outputs.jsonl']['path']).read_text().splitlines()]
    assert raw(a)==raw(b)
    assert [(m.metric_name,m.metric_value,m.metadata['condition']) for m in snap.metrics if m.run_id==a.run_id]==[(m.metric_name,m.metric_value,m.metadata['condition']) for m in snap.metrics if m.run_id==b.run_id]
    assert valid_result(snap,a) and valid_result(snap,b)
    with ResearchLedger(runtime.ledger.database.path) as reopened:
        saved=load_snapshot(reopened,PROJECT); assert saved.runs==snap.runs and valid_result(saved,b)


@pytest.mark.parametrize('defect',['approval','readiness','audit','checks','code','resource','manifest','spec','blocker','adapter'])
def test_preflight_rejects_before_child_and_no_run_or_metric(ready_runtime,defect,monkeypatch):
    runtime,service,spec=ready_runtime; snap=snapshot(ready_runtime)
    if defect=='code': (Path(current_implementation(snap).code_path)/'experiment.py').write_text('changed')
    elif defect=='resource': Path(snap.resources[0].path_or_uri).write_text('[]')
    elif defect=='adapter': runtime.adapters={}
    else:
        if defect=='approval': snap=snap.model_copy(update={'events':[e for e in snap.events if e.event_type!='HUMAN_APPROVED']})
        elif defect=='readiness': snap=snap.model_copy(update={'readiness':[]})
        elif defect=='audit': snap=snap.model_copy(update={'reviews':[r for r in snap.reviews if r.review_type!='code']})
        elif defect=='checks': snap=snap.model_copy(update={'events':[e for e in snap.events if e.event_type!='IMPLEMENTATION_TESTED']})
        elif defect=='manifest': snap=snap.model_copy(update={'events':[e for e in snap.events if e.event_type!='RESOURCE_MANIFEST_CREATED']})
        elif defect=='spec': snap=snap.model_copy(update={'experiments':[spec.model_copy(update={'version':2})]})
        elif defect=='blocker': snap=snap.model_copy(update={'events':[*snap.events,s.EventRecord(event_id='EV_BLOCK',project_id=PROJECT,event_type='PROJECT_BLOCKED',actor='orchestrator',summary='Unresolved blocker')]})
        monkeypatch.setattr('autolab.runtime.service.load_snapshot',lambda *a:snap)
    async def forbidden(*args,**kwargs): pytest.fail('Preflight allowed child execution')
    monkeypatch.setattr('autolab.runtime.service.execute',forbidden)
    with pytest.raises(RuntimeErrorRecord): run(runtime.run(PROJECT))
    saved=load_snapshot(runtime.ledger,PROJECT)
    assert not saved.runs and not saved.metrics
    assert saved.events[-1].event_type=='EXPERIMENT_RUN_REJECTED'


def test_real_saved_exp_0001_cannot_run():
    check=verify_real_run_blocked()
    if not check['available']: pytest.skip('Ignored saved production artifact absent in clean checkout')
    assert check['rejected'] and check['snapshot_sha256']=='cee272e362ed83c97b13839112c80d50cd8b83996dc28c85ee62377ff119598e'


@pytest.mark.parametrize('mode',['failure','timeout','malformed','missing','failed_sample','excess_output'])
def test_execution_failures_never_publish_final_metrics(ready_runtime,mode):
    def transform(source):
        if mode=='failure': return source.replace('    def run(self, context):\n','    def run(self, context):\n        raise RuntimeError("Controlled failure")\n')
        if mode=='timeout': return source.replace('    def run(self, context):\n','    def run(self, context):\n        while True:\n            value = 1\n')
        if mode=='malformed': return source.replace('"observations":self.observations','"observations":[{"bad":"shape"}]')
        if mode=='missing': return source.replace('self.observations = observations','self.observations = observations[:-1]')
        if mode=='failed_sample': return source.replace('self.observations = observations','observations[0]["status"] = "failed"\n        observations[0]["failure_category"] = "rule_error"\n        observations[0]["outputs"]["error"] = "Controlled sample failure"\n        self.observations = observations')
        return source.replace('self.observations = observations','self.observations = observations * 10000')
    replace_implementation(ready_runtime,transform)
    runtime,*_=ready_runtime
    record=run(runtime.run(PROJECT,timeout_seconds=.05 if mode=='timeout' else 5,max_output_bytes=4096 if mode=='excess_output' else 262144))
    snap=snapshot(ready_runtime)
    assert record.status==(s.RunStatus.TIMED_OUT if mode=='timeout' else s.RunStatus.FAILED)
    assert record.error_message and not snap.metrics and record.output_manifest['partial']
    assert not valid_result(snap,record) and not DecisionValidator().validate(decision(snap,'ANALYZE_RESULT','analyst'),snap).valid
    assert derive_control_state(snap)==C.ADAPTIVE_DECISION and not active_run(snap)
    assert Path(record.output_manifest['artifacts']['stderr.log']['path']).exists()
    assert record.output_manifest['artifacts']['stdout.log']['size']<=8192
    if mode=='failed_sample':
        raw=Path(record.output_manifest['artifacts']['raw_outputs.jsonl']['path']).read_text()
        assert 'Controlled sample failure' in raw and record.output_manifest['observation_count']==8
    assert_no_analysis(snap)


@pytest.mark.parametrize('artifact',['raw_outputs.jsonl','metrics.json','config.json'])
def test_tampered_result_artifact_blocks_analysis(ready_runtime,artifact):
    runtime,*_=ready_runtime; record=run(runtime.run(PROJECT)); snap=snapshot(ready_runtime)
    path=Path(record.output_manifest['artifacts'][artifact]['path']); before=path.read_bytes(); path.write_bytes(before+b' ')
    assert not valid_result(snap,record)
    assert not DecisionValidator().validate(decision(snap,'ANALYZE_RESULT','analyst'),snap).valid
    assert path.read_bytes()==before+b' '  # Validator must not repair or overwrite history.


@pytest.mark.parametrize('defect',['missing','foreign_run','foreign_spec','denominator','value','missing_secondary'])
def test_metric_integrity_required_for_analysis(ready_runtime,defect):
    runtime,*_=ready_runtime; record=run(runtime.run(PROJECT)); snap=snapshot(ready_runtime)
    metrics=snap.metrics
    if defect=='missing': metrics=[]
    elif defect=='missing_secondary':
        snap=snap.model_copy(update={'experiments':[snap.experiments[0].model_copy(update={'secondary_metrics':['preregistered_other']})]})
    else:
        change={'foreign_run':{'run_id':'RUN_FOREIGN'},'foreign_spec':{'experiment_version':2},
                'denominator':{'metadata':{**metrics[0].metadata,'denominator':3}},'value':{'metric_value':9.0}}[defect]
        metrics=[metrics[0].model_copy(update=change),*metrics[1:]]
    snap=snap.model_copy(update={'metrics':metrics})
    assert not valid_result(snap,record) and not DecisionValidator().validate(decision(snap,'ANALYZE_RESULT','analyst'),snap).valid


def test_workspace_symlink_and_existing_directory_rejected(ready_runtime,tmp_path):
    runtime,*_=ready_runtime; outside=tmp_path/'outside';outside.mkdir()
    (tmp_path/'experiments/EXP_PHASE10/runs').symlink_to(outside,target_is_directory=True)
    with pytest.raises(RuntimeErrorRecord,match='Unconfined'): run(runtime.run(PROJECT))
    assert not list(outside.iterdir()) and not snapshot(ready_runtime).runs


def test_orchestrator_executes_once_and_returns_planner_control(ready_runtime):
    runtime,*_=ready_runtime
    class Planner:
        async def propose(self,context,decision_id,feedback=None):
            return decision(snapshot(ready_runtime),identifier=decision_id).model_dump_json()
    orchestrator=Orchestrator(runtime.ledger,Planner()); route=run(orchestrator.decide(PROJECT))
    record=run(orchestrator.execute_runtime(route,runtime)); snap=snapshot(ready_runtime)
    assert record.status==s.RunStatus.COMPLETED and snap.events[-1].event_type=='SPECIALIST_COMPLETED'
    with pytest.raises(IllegalDecisionError,match='already dispatched'): run(orchestrator.execute_runtime(route,runtime))
    assert len(snap.runs)==1; assert_no_analysis(snap)


def test_secrets_and_network_unavailable_even_if_static_admission_missed(ready_runtime,monkeypatch):
    runtime,*_=ready_runtime
    monkeypatch.setenv('OPENAI_API_KEY','secret-parent-only');monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','also-secret')
    from autolab.runtime.process import execute as real_execute
    async def inject(payload,config,**kwargs):
        payload={**payload,'files':{**payload['files'],'experiment.py':payload['files']['experiment.py']+'\nimport socket\n'}}
        return await real_execute(payload,config,**kwargs)
    monkeypatch.setattr('autolab.runtime.service.execute',inject)
    record=run(runtime.run(PROJECT)); assert record.status==s.RunStatus.FAILED
    logs=''.join(Path(pin['path']).read_text() for name,pin in record.output_manifest['artifacts'].items() if name.endswith('.log'))
    assert 'ImportError' in logs and 'secret-parent-only' not in logs and 'also-secret' not in logs


def test_no_runtime_reasoning_model_or_llm_calls(ready_runtime,monkeypatch):
    async def forbidden(*a,**k): pytest.fail('Runtime called an AutoLab LLM')
    monkeypatch.setattr('autolab.planner.service.OmnigentPlanner.invoke_agent',forbidden)
    assert run(ready_runtime[0].run(PROJECT)).status==s.RunStatus.COMPLETED


def test_runtime_limits_cannot_change_seed_network_or_retry_scope(ready_runtime):
    runtime,*_=ready_runtime
    for kwargs in ({'seed':20},{'network_policy':'online'},{'retries':1}):
        with pytest.raises(TypeError): run(runtime.run(PROJECT,**kwargs))
    with pytest.raises(RuntimeErrorRecord): run(runtime.run(PROJECT,timeout_seconds=4000))
    assert not snapshot(ready_runtime).runs


def test_partial_observations_survive_collector_failure(ready_runtime):
    replace_implementation(ready_runtime,lambda src:src.replace('    def collect_results(self, context):\n',
        '    def collect_results(self, context):\n        raise RuntimeError("Controlled collection failure")\n'))
    # The handwritten fixture calls collect_results in run. Publish its raw
    # state before this error; the worker preserves it as partial evidence.
    record=run(ready_runtime[0].run(PROJECT));snap=snapshot(ready_runtime)
    assert record.status==s.RunStatus.FAILED and record.output_manifest['observation_count']==8
    assert not snap.metrics and record.environment_metadata['usage']['calls']==8


def test_cancelled_process_is_terminated_and_recorded(ready_runtime):
    replace_implementation(ready_runtime,lambda src:src.replace('    def run(self, context):\n',
        '    def run(self, context):\n        while True:\n            value = 1\n'))
    async def cancel():
        task=asyncio.create_task(ready_runtime[0].run(PROJECT))
        await asyncio.sleep(.08); task.cancel()
        return await task
    record=run(cancel());snap=snapshot(ready_runtime)
    assert record.status==s.RunStatus.CANCELLED and not snap.metrics and not active_run(snap)
    assert record.environment_metadata['exit_status']!=0


def test_child_launch_failure_finalizes_without_ledger_corruption(ready_runtime,monkeypatch):
    async def crash(*a,**k): raise OSError('Controlled process launch failure')
    monkeypatch.setattr('autolab.runtime.service.execute',crash)
    record=run(ready_runtime[0].run(PROJECT));snap=snapshot(ready_runtime)
    assert record.status==s.RunStatus.FAILED and 'launch failure' in record.error_message
    assert not active_run(snap) and not snap.metrics
    assert snap.events[-1].event_type=='EXPERIMENT_RUN_FAILED'


def test_changed_dependencies_during_execution_prevent_final_metrics(ready_runtime,monkeypatch):
    from autolab.runtime.process import execute as real
    runtime,*_=ready_runtime
    async def mutate(payload,config,**kwargs):
        receipt=await real(payload,config,**kwargs)
        if payload['mode']=='metrics':
            path=Path(snapshot(ready_runtime).resources[0].path_or_uri);path.write_text('[]')
        return receipt
    monkeypatch.setattr('autolab.runtime.service.execute',mutate)
    record=run(runtime.run(PROJECT));snap=snapshot(ready_runtime)
    assert record.status==s.RunStatus.FAILED and record.output_manifest['observation_count']==8
    assert 'changed' in record.error_message and not snap.metrics


@pytest.mark.parametrize('attempt',["open('/tmp/forbidden-runtime-write','w')", "import os\nos.environ['OPENAI_API_KEY']", 'import socket'])
def test_worker_denies_file_secret_and_network_capabilities(ready_runtime,monkeypatch,attempt):
    from autolab.runtime.process import execute as real
    async def inject(payload,config,**kwargs):
        files={**payload['files']};files['experiment.py']+='\n'+attempt+'\n'
        return await real({**payload,'files':files},config,**kwargs)
    monkeypatch.setattr('autolab.runtime.service.execute',inject)
    record=run(ready_runtime[0].run(PROJECT))
    assert record.status==s.RunStatus.FAILED and not snapshot(ready_runtime).metrics


def test_metric_oracle_disagreement_is_integrity_failure(ready_runtime,monkeypatch):
    runtime,*_=ready_runtime
    adapter=next(iter(runtime.adapters.values()))
    monkeypatch.setattr(adapter,'independently_recompute',lambda *a:9.0)
    record=run(runtime.run(PROJECT))
    assert record.status==s.RunStatus.FAILED and 'independent raw' in record.error_message
    assert not snapshot(ready_runtime).metrics


def test_unregistered_metric_request_is_rejected(ready_runtime,monkeypatch):
    runtime,*_=ready_runtime;adapter=next(iter(runtime.adapters.values()));original=adapter.metric_jobs
    def wrong(*args):
        jobs=original(*args)
        return [*jobs,jobs[0].model_copy(update={'metric_name':'post_hoc_metric','role':'secondary'})]
    monkeypatch.setattr(adapter,'metric_jobs',wrong)
    record=run(runtime.run(PROJECT))
    assert record.status==s.RunStatus.FAILED and 'Unregistered' in record.error_message
    assert not snapshot(ready_runtime).metrics


@pytest.mark.parametrize('secondary',[False,True])
def test_null_scientific_difference_is_completed_and_secondary_requires_preregistration(ledger,tmp_path,secondary):
    rows=[{'sample_id':f'null-{i}','prediction':.2+i*.1,'target':.6} for i in range(4)]
    _,spec,contract=run(seed_fixture(ledger,tmp_path,project_id=PROJECT,experiment_id='EXP_PHASE10',execution_fixture=True,
        resource_rows=rows,secondary_metrics=['sum_absolute_error'] if secondary else []))
    def source(files):
        files={n:v.replace('EXP_PHASE9','EXP_PHASE10') for n,v in files.items()}
        if secondary: files['experiment.py']+='\ndef compute_error_sum(predictions,targets):\n    return compute_mae(predictions,targets) * len(targets)\n'
        return files
    implementation=ImplementationService(ledger,Implementer(mutate_source=source),Auditor(),root=tmp_path,contracts={spec_fingerprint(spec):contract})
    run(implementation.run(PROJECT));record=current_implementation(load_snapshot(ledger,PROJECT));authorize_execution(ledger,record)
    class Adapter(ScalarFixtureAdapter):
        adapter_id='paired-null-scalar-with-preregistered-sum-v1'
        supported_metrics={'mean_absolute_error','sum_absolute_error'}
        def metric_jobs(self,observations,resources,plan):
            from autolab.runtime.models import MetricJob
            primary=plan.model_copy(update={'metrics':{spec.primary_metric:plan.metrics[spec.primary_metric]}})
            jobs=super().metric_jobs(observations,resources,primary)
            return jobs+[MetricJob(**{**job.model_dump(mode='json'),'metric_name':'sum_absolute_error','role':'secondary',
                'component':plan.metrics['sum_absolute_error']}) for job in jobs] if secondary else jobs
        def independently_recompute(self,job,observations):
            primary=job.model_copy(update={'metric_name':'mean_absolute_error'})
            value=super().independently_recompute(primary,observations)
            return value*job.denominator if job.role=='secondary' else value
    runtime=ExperimentRuntime(ledger,root=tmp_path,adapters={spec_fingerprint(spec):Adapter(spec_fingerprint(spec))})
    result=run(runtime.run(PROJECT));snap=load_snapshot(ledger,PROJECT)
    assert result.status==s.RunStatus.COMPLETED and valid_result(snap,result)
    primary=[m for m in snap.metrics if m.metadata['role']=='primary']
    assert primary[0].metric_value==primary[1].metric_value  # No improvement is still COMPLETED.
    assert len(snap.metrics)==(4 if secondary else 2)
    if secondary: assert all(math.isclose(m.metric_value,primary[0].metric_value*4) for m in snap.metrics if m.metadata['role']=='secondary')


def test_validation_failure_receipt_identifies_test_counts_and_software(ready_runtime):
    runtime,service,spec=ready_runtime
    original=service.implementer
    def fail(files):
        files={n:v.replace('EXP_PHASE9','EXP_PHASE10') for n,v in files.items()}
        files['test_experiment.py']+='\ndef test_controlled_assertion_failure():\n    assert False, "Controlled assertion"\n'
        return files
    service.auditor=Auditor(sequence=['REVISE']);previous=current_implementation(snapshot(ready_runtime));review=run(service.audit(PROJECT))
    service.implementer=Implementer(mutate_source=fail)
    record=run(service.implement(PROJECT,previous=previous,review=review));checks=record.metadata['checks'];detail=json.loads(checks['output'])
    assert not checks['tests_pass'] and checks['exit_status']==1
    assert checks['test_count']==17 and checks['generated_count']==4
    assert detail['stage']=='generated: test_controlled_assertion_failure'
    assert detail['validation_environment']['python_version'] and len(detail['validation_environment']['framework_source_sha256'])==64


def test_fixture_import_rebinds_plan_tests_and_source_revision(ready_runtime):
    from autolab.runtime_smoke_helpers import ReboundFixtureSource
    from autolab.implementation.models import ImplementationPlan
    runtime,service,spec=ready_runtime
    record=current_implementation(snapshot(ready_runtime));old_plan=ImplementationPlan.model_validate(record.metadata['plan'])
    # Exercise the actual audited Phase 9 text when available; clean checkouts
    # retain equivalent deterministic plan/source coverage through other tests.
    path=Path(__file__).parents[1]/'results/phase9-code-audit-smoke.json'
    if not path.exists(): pytest.skip('Ignored Phase 9 generated fixture unavailable')
    from autolab.orchestration.models import ProjectSnapshot
    old=current_implementation(ProjectSnapshot.model_validate(json.loads(path.read_text())['snapshot']))
    importer=ReboundFixtureSource(old)
    assignment={key:getattr(old_plan,key) for key in ('project_id','experiment_id','experiment_version','implementation_id','revision','spec_fingerprint','manifest_fingerprint','readiness_id')}
    context={'resource_manifest':{'resources':[p.model_dump(mode='json') for p in old_plan.input_resources]},'raw_output_schema':old_plan.output_schema}
    plan=run(importer.plan(context,assignment));bundle=run(importer.generate(context,plan))
    assert 'context.experiment_id EXP_PHASE9' not in str(plan.reproducibility)
    assert "'approved_plan_revision': 0" in bundle.files['experiment.py']
    assert "metadata['approved_plan_revision'] == 0" in bundle.files['test_experiment.py']
    assert 'approved plan revision 0' in bundle.files['experiment.py']


def test_active_run_prevents_duplicate_execution(ready_runtime):
    runtime,*_=ready_runtime
    event=runtime.event(PROJECT,'EXPERIMENT_RUN_STARTED','RUN_ACTIVE',config={})
    runtime.ledger.add_event(event);snap=snapshot(ready_runtime)
    assert derive_control_state(snap)==C.RUNNING
    assert not DecisionValidator().validate(decision(snap),snap).valid
    with pytest.raises(RuntimeErrorRecord): run(runtime.run(PROJECT))
    assert not snapshot(ready_runtime).runs


def test_run_directory_never_overwrites_existing_artifacts(ready_runtime,tmp_path):
    runtime,*_=ready_runtime
    root=tmp_path/'experiments/EXP_PHASE10/runs/RUN_0001';root.mkdir(parents=True)
    sentinel=root/'config.json';sentinel.write_text('previous evidence')
    with pytest.raises(FileExistsError): run(runtime.run(PROJECT))
    assert sentinel.read_text()=='previous evidence' and not snapshot(ready_runtime).runs


def test_raw_envelope_size_limit_is_explicit_failure(ready_runtime):
    # Bare observations fit the pipe, but provenance-wrapped rows exceed 4096.
    record=run(ready_runtime[0].run(PROJECT,max_output_bytes=4096))
    assert record.status==s.RunStatus.FAILED and 'limit exceeded' in record.error_message
    assert record.output_manifest['artifacts']['raw_outputs.jsonl']['size']<=4096
    assert record.output_manifest['unpublished_observation_count']>0
    assert not snapshot(ready_runtime).metrics


def test_negative_usage_counter_is_not_accepted_as_completed(ready_runtime):
    replace_implementation(ready_runtime,lambda src:src.replace('self.observations = observations',
        'observations[0]["counts"]["tokens"] = -1\n        self.observations = observations'))
    record=run(ready_runtime[0].run(PROJECT))
    assert record.status==s.RunStatus.FAILED and 'Negative' in record.error_message
    assert 'tokens' not in record.environment_metadata['usage'] and record.environment_metadata['usage']['invalid_usage_counters']==['tokens']
    assert not snapshot(ready_runtime).metrics


def test_existing_runner_exposes_gated_canonical_runtime(ready_runtime):
    from tools.experiment_runner import run_approved_experiment
    runtime,*_=ready_runtime
    record=run(run_approved_experiment(runtime.ledger,PROJECT,adapters=runtime.adapters,root=runtime.root))
    assert record.status==s.RunStatus.COMPLETED and valid_result(snapshot(ready_runtime),record)
