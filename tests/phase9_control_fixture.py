"""Explicit control-plane test provenance for pre-existing successful fixtures.

These records model trusted validation/audit events; no scientific code is run.
Actual worker fidelity is tested separately in test_implementation.py.
"""
import hashlib
from autolab import schemas as s
from autolab.implementation.models import ImplementationPlan, TestContract, Probe, CheckReport
from autolab.implementation.persistence import implementation_pins
from autolab.implementation.validation import source_hash, required_requirements
from autolab.preparation.manifest import current_manifest, fingerprint
from autolab.orchestration.state_machine import selected_experiment, current_readiness


def pin_control_fixture(snapshot, tmp_path):
    record = snapshot.implementations[0]; spec = selected_experiment(snapshot); manifest = current_manifest(snapshot)
    artifact = tmp_path.resolve()/'control-implementation'; artifact.mkdir()
    code = artifact/'source'; code.mkdir()
    source = '''from autolab.implementation.contract import BaseExperiment
def metric_fixture(values):
    if not values:
        raise ValueError("Empty control fixture")
    return sum(values) / len(values)
class Experiment(BaseExperiment):
    def setup(self, context):
        self.fixture = context
    def run(self, context):
        raise RuntimeError("Control fixture never executes science")
    def collect_results(self, context):
        return self.fixture
'''
    source += 'EXPERIMENT_ID = ' + repr(spec.experiment_id) + '\nSPEC_HASH = ' + repr(manifest.spec_fingerprint) + '\n'
    source += 'RESOURCE_PINS = ' + repr({p.resource_id:p.checksum for p in manifest.resources}) + '\n'
    files = {'experiment.py':source, 'test_experiment.py':'def test_control_fixture():\n    assert True\n'}
    for n,v in files.items(): (code/n).write_text(v)
    metrics = {n:'experiment.py:metric_fixture' for n in [spec.primary_metric,*spec.secondary_metrics]}
    contract = TestContract(spec_fingerprint=manifest.spec_fingerprint, probes=[Probe(component='experiment.py:metric_fixture',
        expected=1, requirement='Explicit control fixture validation')], required_components=['experiment.py:metric_fixture'],
        metric_requirements=metrics, expected_seeds=[], provenance='Controlled mocked control-plane validator, no scientific execution')
    plan = ImplementationPlan(project_id=record.project_id, experiment_id=record.experiment_id, experiment_version=record.experiment_version,
        implementation_id=record.implementation_id, revision=0, spec_fingerprint=manifest.spec_fingerprint,
        manifest_fingerprint=fingerprint(manifest), readiness_id=current_readiness(snapshot).readiness_id,
        objective=spec.objective, input_resources=manifest.resources, expected_files=list(files), components=['experiment.py:metric_fixture'],
        conditions=spec.independent_variables, baseline=spec.controls, metrics=metrics, reproducibility=['Offline control-plane fixture'], seeds=[],
        output_schema={}, tests=['Explicit mocked framework control test'], limitations=['No actual scientific code or run'],
        requirement_mapping=[{'requirement':f,'component':'experiment.py:metric_fixture','rationale':'Control fixture only'} for f in required_requirements(spec)])
    checks = CheckReport(static_pass=True, tests_pass=True, test_count=1, generated_count=1, exit_status=0)
    for n,obj in [('implementation_plan.json',plan),('test_contract.json',contract),('checks.json',checks)]:
        (artifact/n).write_text(obj.model_dump_json())
    record = record.model_copy(update={'code_path':str(code), 'code_version':source_hash(files),'status':'AUDIT_PENDING',
        'metadata':{'phase':9,'revision':0,'artifact_path':str(artifact),'plan':plan.model_dump(mode='json'),'plan_fingerprint':fingerprint(plan),
            'test_contract':contract.model_dump(mode='json'),'test_contract_fingerprint':fingerprint(contract),
            'checks':checks.model_dump(mode='json'),'file_hashes':{n:hashlib.sha256(v.encode()).hexdigest() for n,v in files.items()}}})
    pins = implementation_pins(snapshot,record)
    record = record.model_copy(update={'metadata':{**record.metadata,'pins':pins}})
    review_bindings = {**pins,'checks_fingerprint':fingerprint(checks)}
    reviews = [r.model_copy(update={'reviewer_role':'code_auditor','metadata':review_bindings,'created_at':s.utc_now()}) if r.review_type=='code' else r for r in snapshot.reviews]
    review = next(r for r in reviews if r.review_type=='code')
    events = [e.model_copy(update={'actor':'implementation_validator','target_type':'implementations','target_id':record.implementation_id,
        'payload':{**e.payload,'pins':pins,'checks':checks.model_dump(mode='json'),'checks_fingerprint':fingerprint(checks)}}) if e.event_type=='IMPLEMENTATION_TESTED' else e for e in snapshot.events]
    events.append(s.EventRecord(event_id='EVENT_CODE_APPROVED_FIXTURE',project_id=record.project_id,event_type='IMPLEMENTATION_APPROVED',
        actor='implementation_validator',target_type='implementations',target_id=record.implementation_id,
        summary='Explicit mocked control-plane audit gate',payload={'pins':review_bindings,'review_id':review.review_id}))
    return snapshot.model_copy(update={'implementations':[record],'reviews':reviews,'events':events})
