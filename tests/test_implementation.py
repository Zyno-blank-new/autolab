"""Phase 9 gate, safety, scientific-fidelity, audit and revision regressions."""
import json
from pathlib import Path
import pytest
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import current_implementation, implementation_passes, derive_control_state
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.orchestrator import Orchestrator, IllegalDecisionError
from autolab.preparation.manifest import current_manifest, fingerprint
from autolab.implementation.service import ImplementationService
from autolab.implementation.models import ImplementationError, ImplementationPlan, ImplementationResult
from autolab.implementation.validation import static_checks, read_sources, source_hash
from autolab.implementation.harness import run_checks, sanitized_environment
from autolab.implementation_smoke_helpers import seed_fixture, PROJECT, decision, assert_no_execution, verify_real_blocked, approve_fixture_run_eligibility
from phase9_helpers import Implementer, Auditor, sources, run


@pytest.fixture
def fixture(ledger,tmp_path):
    project,spec,contract=run(seed_fixture(ledger,tmp_path))
    service=ImplementationService(ledger,Implementer(),Auditor(),root=tmp_path,contracts={contract.spec_fingerprint:contract})
    return service,project,spec,contract


def snapshot(fixture): return load_snapshot(fixture[0].ledger,PROJECT)


@pytest.mark.parametrize('defect',['no_readiness','blocked_readiness','stale_readiness','no_manifest','stale_approval','spec_version','resource_hash','material_block'])
def test_preconditions_fail_before_code(fixture,defect):
    service,p,e,c=fixture; snap=snapshot(fixture)
    if defect=='no_readiness': snap=snap.model_copy(update={'readiness':[]})
    elif defect=='blocked_readiness': snap=snap.model_copy(update={'readiness':[snap.readiness[0].model_copy(update={'verdict':'BLOCK'})]})
    elif defect=='stale_readiness': snap=snap.model_copy(update={'readiness':[snap.readiness[0].model_copy(update={'metadata':{}})]})
    elif defect=='no_manifest': snap=snap.model_copy(update={'events':[v for v in snap.events if v.event_type!='RESOURCE_MANIFEST_CREATED']})
    elif defect=='stale_approval': snap=snap.model_copy(update={'events':[v for v in snap.events if v.event_type!='HUMAN_APPROVED']})
    elif defect=='spec_version': snap=snap.model_copy(update={'experiments':[e.model_copy(update={'version':2})]})
    elif defect=='resource_hash': Path(snap.resources[0].path_or_uri).write_text('[]')
    elif defect=='material_block': snap=snap.model_copy(update={'events':[*snap.events,s.EventRecord(event_id='EV_BLOCK',project_id=p.project_id,event_type='PROJECT_BLOCKED',actor='orchestrator',summary='Unresolved blocker')]})
    assert not DecisionValidator().validate(decision(snap),snap).valid
    with pytest.raises(ImplementationError): service._gate(snap)
    assert service.implementer.plan_calls==0 and not snap.implementations


def test_actual_saved_blocked_state_never_implements(fixture):
    check=verify_real_blocked()
    if not check['available']: pytest.skip('Actual ignored saved state absent in clean checkout')
    assert check['rejected'] and check['saved_snapshot_sha256']
    path=Path(check['database_path'])
    # Compare real SQLite read-only as well; never initialize or write this database.
    import sqlite3
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        assert db.execute('select count(*) from implementations').fetchone()[0]==0


@pytest.mark.parametrize('field,value',[('objective','Changed science'),('baseline',{}),('conditions',{}),
    ('spec_fingerprint','wrong'),('experiment_version',2),('input_resources',[]),('seeds',[]),
    ('requirement_mapping',[]),('dependencies',['requests']),('expected_files',['../../.env','experiment.py'])])
def test_plan_cannot_change_contract(fixture,field,value):
    service,p,e,c=fixture
    service.implementer=Implementer(mutate_plan=lambda plan:plan.model_copy(update={field:value}))
    with pytest.raises((ImplementationError,ValueError)): run(service.implement(PROJECT))
    assert not snapshot(fixture).implementations and service.implementer.code_calls==0


def test_plan_first_pins_and_focused_context(fixture):
    service,p,e,c=fixture; record=run(service.implement(PROJECT)); snap=snapshot(fixture)
    plan=ImplementationPlan.model_validate(record.metadata['plan'])
    assert plan.input_resources==current_manifest(snap).resources and plan.requirement_mapping and plan.reproducibility
    events=[v.event_type for v in snap.events]
    assert events.index('IMPLEMENTATION_PLAN_CREATED')<events.index('IMPLEMENTATION_CREATED')
    context=service.implementer.contexts[0]
    assert not {'literature','events','credentials','reasoning','hypotheses'} & set(context)
    assert record.metadata['checks']['tests_pass'] and record.metadata['checks']['generated_count']==4
    assert not implementation_passes(snap) and derive_control_state(snap)=='CODE_REVIEW'


@pytest.mark.parametrize('addition',["import subprocess", "import os", "import socket", "import requests", "import pathlib",
    "eval('1')", "exec('x=1')", "open('.env')", "open('/Users/person/.aws/credentials')", "getattr(x,'system')",
    "import math\nmath.__dict__", "import json\njson.load(x)", "import urllib.request", "import shutil",
    "x = globals()", "x = __builtins__", "import random\nx=random.random()"])
def test_unsafe_source_rejected_before_worker(fixture,addition,monkeypatch):
    service,p,e,c=fixture
    service.implementer=Implementer(mutate_source=lambda files:{**files,'experiment.py':files['experiment.py']+'\n'+addition+'\n'})
    import autolab.implementation.harness as harness
    async def forbidden_spawn(*a,**k): raise AssertionError('Unsafe source reached process')
    monkeypatch.setattr(harness.asyncio,'create_subprocess_exec',forbidden_spawn)
    record=run(service.implement(PROJECT)); checks=record.metadata['checks']
    assert not checks['static_pass'] and checks['exit_status'] is None and not checks['tests_pass']
    assert not implementation_passes(snapshot(fixture))


@pytest.mark.parametrize('defect',['syntax','interface','metric','todo','pass','hardcoded','wrong_hash','swallow','run_in_test','dunder'])
def test_static_validators(fixture,defect):
    service,p,e,c=fixture
    def change(files):
        src=files['experiment.py']
        if defect=='syntax': src+='\n('
        elif defect=='interface': src=src.replace('def setup(self, context):','def setup(self):')
        elif defect=='metric': src=src.replace('def compute_mae(', 'def missing_metric(')
        elif defect=='todo': src+='\n# TODO implement scoring\n'
        elif defect=='pass': src+='\ndef missing():\n    pass\n'
        elif defect=='hardcoded': src=src.replace('return math.fsum(abs(p-t) for p,t in zip(predictions,targets)) / len(targets)','return 0.95')
        elif defect=='wrong_hash': src=src.replace('RESOURCE_HASH = "','RESOURCE_HASH = "wrong')
        elif defect=='swallow': src+='\ndef hidden_failure():\n    try:\n        raise ValueError("bad")\n    except Exception:\n        return True\n'
        elif defect=='run_in_test': files['test_experiment.py']+='\ndef test_bad():\n    x.run({})\n'
        elif defect=='dunder': src+='\nclass Bad:\n    def __getattribute__(self,x):\n        return x\n'
        return {**files,'experiment.py':src}
    service.implementer=Implementer(mutate_source=change)
    record=run(service.implement(PROJECT)); assert not record.metadata['checks']['static_pass']


@pytest.mark.parametrize('defect',['denominator','baseline','budget','missing_sample'])
def test_syntactically_valid_scientifically_wrong_never_ready(fixture,defect):
    service,p,e,c=fixture
    def change(files):
        src=files['experiment.py']
        if defect=='denominator': src=src.replace('/ len(targets)','/ (len(targets)+1)')
        elif defect=='baseline': src=src.replace('prediction = value','prediction = min(1.0,max(0.0,value))')
        elif defect=='budget': src=src.replace('if max_calls < 1:','if max_calls < -100:')
        elif defect=='missing_sample': src=src.replace('if not predictions or len(predictions) != len(targets):','if not predictions:')
        return {**files,'experiment.py':src}
    service.implementer=Implementer(mutate_source=change)
    result=run(service.run(PROJECT)); record=current_implementation(snapshot(fixture))
    assert record.metadata['checks']['static_pass'] and not record.metadata['checks']['tests_pass']
    assert result.status=='BLOCK' and not implementation_passes(snapshot(fixture))


@pytest.mark.parametrize('verdict',['PASS','REVISE','REJECT','BLOCK'])
def test_independent_review_verdicts_persist(fixture,verdict):
    service,p,e,c=fixture; service.auditor=Auditor(sequence=[verdict]); record=run(service.implement(PROJECT))
    review=run(service.audit(PROJECT)); snap=snapshot(fixture)
    assert review.verdict==verdict and review in snap.reviews and review.metadata['code_hash']==record.code_version
    assert implementation_passes(snap)==(verdict=='PASS')
    assert 'files' in service.auditor.contexts[0] and 'reasoning' not in json.dumps(service.auditor.contexts[0])


@pytest.mark.parametrize('pin',['code_hash','spec_fingerprint','manifest_fingerprint','resource_pins','readiness_id'])
def test_wrong_audit_pins_rejected(fixture,pin):
    service,p,e,c=fixture; run(service.implement(PROJECT))
    service.auditor=Auditor(mutate=lambda review:review.model_copy(update={'metadata':{**review.metadata,pin:'wrong'}}))
    with pytest.raises(ImplementationError,match='pins differ'): run(service.audit(PROJECT))
    assert not implementation_passes(snapshot(fixture))


@pytest.mark.parametrize('response',['ACCEPT','REJECT','NEEDS_CLARIFICATION'])
def test_bounded_revision_and_rebuttal_history(fixture,response):
    service,p,e,c=fixture; service.implementer=Implementer(response=response)
    service.auditor=Auditor(sequence=['REVISE','PASS'])
    result=run(service.run(PROJECT)); snap=snapshot(fixture)
    assert result.status=='READY' and result.revision_rounds==1 and len(snap.implementations)==2
    assert len(result.review_ids)==2 and service.implementer.code_calls==2
    old,new=snap.implementations
    assert new.metadata['previous_code_hash']==old.code_version and new.metadata['previous_implementation_id']==old.implementation_id
    assert new.metadata['plan']['issue_responses'][0]['disposition']==response
    assert Path(old.code_path).is_dir() and len(snap.reviews)==3
    assert service.auditor.contexts[1]['implementation_plan']['issue_responses'][0]['disposition']==response


def test_revision_limit_returns_control_and_cannot_restart(fixture):
    service,p,e,c=fixture; service.auditor=Auditor(sequence=['REVISE'])
    result=run(service.run(PROJECT)); snap=snapshot(fixture)
    assert result.status=='BLOCK' and result.revision_rounds==2
    assert service.auditor.calls==3 and service.implementer.plan_calls==3 and len(snap.implementations)==3
    assert derive_control_state(snap)=='ADAPTIVE_DECISION' and not implementation_passes(snap)
    with pytest.raises(ImplementationError,match='already exists'): run(service.implement(PROJECT))


@pytest.mark.parametrize('change',['source','extra_file','symlink','manifest','resource','spec','readiness','plan','checks','review_hash','review_role','tests_event'])
def test_changed_dependencies_invalidate_execution(fixture,change):
    service,p,e,c=fixture; run(service.run(PROJECT)); snap=snapshot(fixture); record=current_implementation(snap)
    approve_fixture_run_eligibility(service.ledger,record); snap=snapshot(fixture)
    assert DecisionValidator().validate(decision(snap,'RUN_EXPERIMENT','experiment_runner'),snap).valid
    if change=='source': (Path(record.code_path)/'experiment.py').write_text('changed')
    elif change=='extra_file': (Path(record.code_path)/'surprise.py').write_text('x=1')
    elif change=='symlink':
        path=Path(record.code_path)/'experiment.py'; target=path.parent.parent/'outside.py'; path.rename(target); path.symlink_to(target)
    elif change=='manifest': Path(current_manifest(snap).manifest_path).write_text('{}')
    elif change=='resource': Path(snap.resources[0].path_or_uri).write_text('[]')
    elif change=='spec': snap=snap.model_copy(update={'experiments':[e.model_copy(update={'version':2})]})
    elif change=='readiness': snap=snap.model_copy(update={'readiness':[snap.readiness[0].model_copy(update={'metadata':{}})]})
    elif change=='plan': (Path(record.metadata['artifact_path'])/'implementation_plan.json').write_text('{}')
    elif change=='checks': (Path(record.metadata['artifact_path'])/'checks.json').write_text('{}')
    elif change.startswith('review_'):
        review=snap.reviews[-1]; updates={'metadata':{**review.metadata,'code_hash':'wrong'}} if change=='review_hash' else {'reviewer_role':'implementer'}
        snap=snap.model_copy(update={'reviews':[*snap.reviews[:-1],review.model_copy(update=updates)]})
    elif change=='tests_event': snap=snap.model_copy(update={'events':[v for v in snap.events if v.event_type!='IMPLEMENTATION_TESTED']})
    assert not implementation_passes(snap) and not DecisionValidator().validate(decision(snap,'RUN_EXPERIMENT','experiment_runner'),snap).valid


def test_eligibility_after_all_pass_with_exact_test_human_scope(fixture):
    service,p,e,c=fixture; record=run(service.implement(PROJECT)); snap=snapshot(fixture)
    approve_fixture_run_eligibility(service.ledger,record); snap=snapshot(fixture)
    assert not DecisionValidator().validate(decision(snap,'RUN_EXPERIMENT','experiment_runner'),snap).valid
    run(service.audit(PROJECT)); snap=snapshot(fixture)
    assert DecisionValidator().validate(decision(snap,'RUN_EXPERIMENT','experiment_runner'),snap).valid
    assert derive_control_state(snap)=='READY_TO_RUN'
    ctx=ContextBuilder().build(snap); summary=ctx.current_records['implementation']
    assert summary['status']=='READY' and summary['tests_pass'] and summary['code_review']=='PASS'
    assert 'files' not in summary and 'source' not in summary
    assert_no_execution(snap)


def test_timeout_environment_and_secrets(fixture,monkeypatch):
    service,p,e,c=fixture
    monkeypatch.setenv('OPENAI_API_KEY','test-secret'); monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','other-secret')
    assert sanitized_environment()=={'PYTHONHASHSEED':'0','LANG':'C','LC_ALL':'C'}
    service.timeout_seconds=0.1
    service.implementer=Implementer(mutate_source=lambda f:{**f,'test_experiment.py':f['test_experiment.py']+'\ndef test_hang():\n    while True:\n        x = 1\n'})
    record=run(service.implement(PROJECT)); checks=record.metadata['checks']
    assert checks['timed_out'] and not checks['tests_pass'] and checks['exit_status'] is not None
    assert 'secret' not in checks['output']


@pytest.mark.parametrize('role',['implementer','auditor'])
def test_malformed_output_bounded_and_no_ledger_corruption(fixture,role):
    service,p,e,c=fixture
    if role=='implementer':
        service.implementer=Implementer(mutate_plan=lambda p:{'bad':'output'})
        with pytest.raises(ValueError): run(service.run(PROJECT))
        assert service.implementer.plan_calls==1 and not snapshot(fixture).implementations
    else:
        service.auditor=Auditor(mutate=lambda r:{'bad':'output'})
        with pytest.raises(ValueError): run(service.run(PROJECT))
        assert service.auditor.calls==1 and len(snapshot(fixture).implementations)==1
    assert not implementation_passes(snapshot(fixture)); assert_no_execution(snapshot(fixture))


def test_orchestrator_returns_planner_control_without_runtime(fixture):
    service,p,e,c=fixture
    class Planner:
        async def propose(self,context,decision_id,feedback=None):
            return decision(snapshot(fixture)).model_copy(update={'decision_id':decision_id}).model_dump_json()
    controller=Orchestrator(service.ledger,Planner()); route=run(controller.decide(PROJECT))
    result=run(controller.execute_implementation(route,service)); assert result.status=='READY'
    snap=snapshot(fixture); assert snap.events[-1].event_type=='SPECIALIST_COMPLETED'; assert_no_execution(snap)
    with pytest.raises(IllegalDecisionError,match='already completed'): run(controller.execute_implementation(route,service))


def test_workspace_symlink_and_source_traversal(fixture,tmp_path):
    service,p,e,c=fixture
    outside=tmp_path/'outside'; outside.mkdir(); (tmp_path/'experiments/EXP_PHASE9/implementation').mkdir(parents=True)
    (tmp_path/'experiments/EXP_PHASE9/implementation/IMPL_0001').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ImplementationError,match='unconfined'): run(service.implement(PROJECT))
    assert not list(outside.iterdir())


def test_unknown_framework_metric_adapter_blocks_before_llm(fixture):
    service,p,e,c=fixture; service.contracts={}
    with pytest.raises(ImplementationError,match='adapter missing'): run(service.implement(PROJECT))
    assert service.implementer.plan_calls==0


def test_immutable_restart_and_independent_readiness_preserved(fixture):
    service,p,e,c=fixture; run(service.run(PROJECT)); snap=snapshot(fixture)
    with ResearchLedger(service.ledger.database.path) as reopened:
        saved=load_snapshot(reopened,PROJECT); assert implementation_passes(saved)
        assert saved.implementations==snap.implementations and saved.reviews==snap.reviews
    assert_no_execution(snap)


@pytest.mark.parametrize('attempt',["import socket\nsocket.socket()", "open('secret-file')", "import os\nos.environ.get('OPENAI_API_KEY')"])
def test_runtime_denies_network_files_and_secret_capabilities_even_if_static_missed(fixture,monkeypatch,attempt):
    service,p,e,c=fixture; record=run(service.implement(PROJECT))
    from autolab.implementation.models import CheckReport
    import autolab.implementation.harness as harness
    plan=ImplementationPlan.model_validate(record.metadata['plan']); files=read_sources(record)
    files['test_experiment.py']+='\ndef test_forbidden():\n'+''.join('    '+line+'\n' for line in attempt.splitlines())
    monkeypatch.setattr(harness,'static_checks',lambda *a:CheckReport(static_pass=True))
    report=run(run_checks(files,plan,c,record.code_path))
    assert not report.tests_pass and report.exit_status==1
    assert 'ImportError' in report.output or 'NameError' in report.output or 'PermissionError' in report.output


def test_generation_failure_paths_do_not_modify_architecture(fixture):
    service,p,e,c=fixture
    def traversal(files): return {**files,'../../docs/ARCHITECTURE.md':'malicious'}
    service.implementer=Implementer(mutate_source=traversal)
    with pytest.raises(ImplementationError,match='file paths'): run(service.implement(PROJECT))
    assert not snapshot(fixture).implementations and not (service.root/'docs/ARCHITECTURE.md').exists()


def test_later_failed_audit_revokes_previous_pass(fixture):
    service,p,e,c=fixture; run(service.run(PROJECT)); assert implementation_passes(snapshot(fixture))
    service.auditor=Auditor(mutate=lambda r:r.model_copy(update={'target_id':'IMPL_WRONG'}))
    with pytest.raises(ImplementationError): run(service.audit(PROJECT))
    assert not implementation_passes(snapshot(fixture))


def test_review_scientific_overreach_maintained_blocks_after_rebuttal_limit(fixture):
    service,p,e,c=fixture; service.implementer=Implementer(response='REJECT'); service.auditor=Auditor(sequence=['REVISE'])
    result=run(service.run(PROJECT)); assert result.status=='BLOCK' and result.revision_rounds==2
    assert service.auditor.contexts[-1]['implementation_plan']['issue_responses'][0]['disposition']=='REJECT'


def test_worker_confirms_sanitized_environment_and_offline_policy(fixture,monkeypatch):
    service,p,e,c=fixture; monkeypatch.setenv('OPENAI_API_KEY','private-parent-only'); monkeypatch.setenv('HOME','/secret/home')
    record=run(service.implement(PROJECT)); output=json.loads(record.metadata['checks']['output'])
    assert output['environment_sanitized'] and output['network_policy']=='offline' and not output['scientific_run']


def test_resume_existing_revise_preserves_bound_without_redundant_audit(fixture):
    service,p,e,c=fixture; service.auditor=Auditor(sequence=['REVISE','PASS'])
    record=run(service.implement(PROJECT)); review=run(service.audit(PROJECT))
    assert service.auditor.calls==1
    result=run(service.run(PROJECT,audit_only=True))
    assert result.status=='READY' and result.revision_rounds==1 and service.auditor.calls==2
    assert result.review_ids[0]==review.review_id
    assert snapshot(fixture).implementations[-1].metadata['previous_code_hash']==record.code_version


def test_missing_canonical_base_import_detected_before_execution(fixture):
    service,p,e,c=fixture
    service.implementer=Implementer(mutate_source=lambda files:{**files,'experiment.py':files['experiment.py'].replace('from autolab.implementation.contract import BaseExperiment\n','')})
    record=run(service.implement(PROJECT))
    assert 'Canonical BaseExperiment import missing' in record.metadata['checks']['findings']
    assert record.metadata['checks']['exit_status'] is None


def test_indirect_run_reference_rejected_in_test_source(fixture):
    service,p,e,c=fixture
    service.implementer=Implementer(mutate_source=lambda files:{**files,'test_experiment.py':files['test_experiment.py']+'\ndef test_indirect():\n    entry = Experiment.run\n'})
    record=run(service.implement(PROJECT))
    assert any('run reference forbidden' in f for f in record.metadata['checks']['findings'])


def test_material_issues_require_responses_and_actionable_corrections(fixture):
    service,p,e,c=fixture; service.auditor=Auditor(sequence=['REVISE'])
    record=run(service.implement(PROJECT)); review=run(service.audit(PROJECT))
    service.implementer=Implementer(mutate_plan=lambda p:p.model_copy(update={'issue_responses':[]}))
    with pytest.raises(ImplementationError,match='every material issue'): run(service.implement(PROJECT,previous=record,review=review))
    service.auditor=Auditor(sequence=['REVISE'],mutate=lambda r:r.model_copy(update={'issues':[{'problem':'Improve robustness'}]}))
    with pytest.raises(ImplementationError,match='actionable'): run(service.audit(PROJECT))


def test_visible_failure_reporting_is_allowed_but_silent_success_is_not(fixture):
    service,p,e,c=fixture; record=run(service.implement(PROJECT)); plan=ImplementationPlan.model_validate(record.metadata['plan'])
    files=read_sources(record)
    files['experiment.py']+='\ndef honest_failure():\n    outputs = {}\n    try:\n        raise ValueError("toy failure")\n    except Exception as error:\n        status = "failed"\n        outputs["error"] = str(error)\n    return {"status":status,"outputs":outputs}\n'
    assert static_checks(files,plan,c).static_pass


def test_revalidation_is_append_only_and_failed_retest_revokes_ready(fixture):
    service,p,e,c=fixture; run(service.run(PROJECT)); before=snapshot(fixture)
    record=current_implementation(before); initial=Path(record.metadata['artifact_path'])/'checks.json'; old=initial.read_bytes()
    service.timeout_seconds=0.0001
    report=run(service.revalidate(PROJECT)); after=snapshot(fixture)
    assert not report.tests_pass and initial.read_bytes()==old and after.implementations==before.implementations
    assert len(after.events)==len(before.events)+1 and not implementation_passes(after)


def test_exact_manifest_provenance_path_and_safe_exception_initialization_allowed(fixture):
    service,p,e,c=fixture; record=run(service.implement(PROJECT)); plan=ImplementationPlan.model_validate(record.metadata['plan'])
    files=read_sources(record)
    files['experiment.py']+='\nRESOURCE_PATH = '+repr(plan.input_resources[0].path)+'\nclass CountedFailure(ValueError):\n    def __init__(self, detail):\n        ValueError.__init__(self, detail)\n        self.calls = 1\n'
    assert static_checks(files,plan,c).static_pass
    files['experiment.py']+='\nFOREIGN = "/Users/person/private.json"\n'
    assert not static_checks(files,plan,c).static_pass


def test_reported_failed_aggregate_is_not_silent_exception_swallowing(fixture):
    service,p,e,c=fixture; record=run(service.implement(PROJECT)); plan=ImplementationPlan.model_validate(record.metadata['plan'])
    files=read_sources(record)
    files['experiment.py']+='\ndef reported_aggregate():\n    errors = []\n    try:\n        raise ValueError("Synthetic failure")\n    except ValueError as error:\n        errors.append(str(error))\n    return {"status":"failed" if errors else "success","error":"; ".join(errors),"metric":None}\n'
    assert static_checks(files,plan,c).static_pass


def test_tampered_retest_report_invalidates_execution(fixture):
    service,p,e,c=fixture; run(service.run(PROJECT)); run(service.revalidate(PROJECT)); snap=snapshot(fixture)
    assert implementation_passes(snap)
    Path(snap.events[-1].payload['report_path']).write_text('{}')
    assert not implementation_passes(snapshot(fixture))


@pytest.mark.parametrize('reported', [True, False])
def test_exception_helper_must_report_failed_status_and_error(fixture, reported):
    service,p,e,c=fixture; record=run(service.implement(PROJECT))
    plan=ImplementationPlan.model_validate(record.metadata['plan']); files=read_sources(record)
    helper_return = '{"status":"failed","error":str(detail),"metric":None}' if reported else 'True'
    files['experiment.py'] += (
        '\ndef failure_receipt(detail):\n    return '+helper_return+
        '\ndef aggregate_with_helper():\n    try:\n        raise ValueError("Synthetic failure")\n'
        '    except ValueError as error:\n        receipt = failure_receipt(error)\n    return receipt\n'
    )
    report=static_checks(files,plan,c)
    assert report.static_pass == reported
    if not reported: assert any('exception silently swallowed' in f for f in report.findings)
