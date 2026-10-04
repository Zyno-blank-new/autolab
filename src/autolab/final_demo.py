"""Small, explicit demo bootstrap and operator contracts; no scientific shortcuts."""
import json
from pathlib import Path
from uuid import uuid4

from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.interface import ProjectService
from autolab.ledger import ResearchLedger
from autolab.feasibility.persistence import spec_fingerprint
from autolab.implementation.models import Probe, TestContract
from autolab.preparation.manifest import current_manifest

PROJECT = 'PROJECT_AUTOLAB_DEMO'
DEMO_ROOT = PROJECT_ROOT / 'results' / 'final-demo'
QUESTION = 'When does range clipping help or harm the reliability of scalar AI predictions compared with leaving predictions unchanged?'
COHORTS = {
    'bounded': [{'sample_id': f'bounded-{i}', 'prediction': p, 'target': t}
        for i, (p, t) in enumerate([(-.2, .1), (.3, .4), (1.2, .9), (.7, .7)])],
    'range_shift': [{'sample_id': f'shift-{i}', 'prediction': p, 'target': t}
        for i, (p, t) in enumerate([(-.2, -.3), (.3, .4), (1.2, 1.3), (.7, .7)])],
}


def create_demo():
    """Always a fresh directory. No imports, deletes or historical DB writes."""
    root = DEMO_ROOT / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    path = root / 'demo.db'
    charter = s.ResearchCharter(project_id=PROJECT, title='AutoLab: an output guardrail under test',
        research_question=QUESTION,
        objective='Decide whether clipping to [0,1] is defensible in one frozen synthetic cohort, with target-domain validity explicitly examined. Demonstrate the reviewed computational scientific loop, not population efficacy or tool-agent behavior.',
        primary_outcome='Condition-wise mean_absolute_error over all four matched samples',
        success_criteria={'decision': 'A reviewed, reproducible condition comparison and a result-sensitive next decision; a negative or inconclusive scientific outcome is valid.'},
        budget_usd=20, max_runtime_minutes=60,
        stop_conditions=['One completed and reviewed comparison followed by a justified decision',
            'Missing scientific prerequisite or unsupported contract',
            'Explicit human rejection, budget/time exhaustion, or call cap'],
        constraints={'max_rounds': 6, 'max_experiments': 1,
            'demo_scope': 'One approved CPU experiment; at most one post-result specialist action. No inference, training, wet lab, external subject model, or general efficacy claim.',
            'operator_supported_protocol': {
                'independent_variables': {'condition': ['baseline', 'clipped'], 'seed': 19, 'max_calls_per_sample': 1},
                'rules': 'baseline identity; clipped min(1,max(0,prediction)); predict receives prediction and condition only; target is scorer-only; all four rows in both conditions in the same order; no missing-row exclusions.',
                'primary_metric': 'mean_absolute_error', 'secondary_metrics': [],
                'resource': 'Exactly one frozen JSON list of four rows with sample_id, prediction, target; required_capabilities=[filesystem_access].',
                'candidate_choices': 'Two distinct candidate cohorts: bounded targets or range_shift targets. The Planner selects. Copy chosen rows into dataset_requirements.frozen_rows before approval. Do not select rows after results.',
                'cohorts': COHORTS,
                'criteria_format': {'success_comparison': {'control': 'baseline', 'intervention': 'clipped', 'direction': 'lower', 'minimum_improvement': 0},
                    'falsification_comparison': {'control': 'baseline', 'intervention': 'clipped', 'direction': 'lower', 'maximum_improvement': 0}},
                'interpretation': 'These are synthetic scalar outputs, not measured AI-model answers. Literature is background/method evidence, not evidence for these future fixture outcomes. Range_shift violates the proposed clipping range on purpose; do not assume targets are bounded for that candidate.'},
            'stop_conditions': ['One completed and reviewed comparison followed by a justified decision', 'Missing scientific prerequisite or unsupported contract', 'Explicit human rejection, budget/time exhaustion, or call cap']})
    with ResearchLedger(path) as ledger:
        ProjectService(ledger).start(charter)
    receipt = {'project_id': PROJECT, 'db': str(path.relative_to(PROJECT_ROOT)), 'mode': 'NEW_CHARTER_ONLY',
        'approval': 'NONE; explicit human action still required'}
    (root / 'setup.json').write_text(json.dumps(receipt, indent=2) + '\n')
    # This pointer identifies only our demo; it never discovers other projects.
    (DEMO_ROOT / 'latest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def require_demo(path):
    path = Path(path).resolve()
    if not path.is_relative_to(DEMO_ROOT.resolve()) or path.name != 'demo.db' or not path.is_file():
        raise ValueError('Select an existing results/final-demo/<namespace>/demo.db created by prepare_demo.')
    with ResearchLedger(path) as ledger:
        charter = ledger.get_project(PROJECT)
        if not charter or charter.research_question != QUESTION:
            raise ValueError('Not an explicit final-demo charter.')
    return path


def supported_spec(spec):
    """Admit only the operator-declared contract; never rewrite a model proposal."""
    variables = spec.independent_variables
    required = {'condition': ['baseline', 'clipped'], 'seed': 19, 'max_calls_per_sample': 1}
    explanatory = {'baseline_rule','clipped_rule','cohort','design_distinction'}
    if any(variables.get(k) != v for k,v in required.items()) or set(variables)-set(required)-explanatory:
        raise ValueError('Designer selected unsupported conditions/seed/budget; preserve proposal and block.')
    rows = spec.dataset_requirements.get('frozen_rows')
    if rows not in COHORTS.values() or spec.primary_metric != 'mean_absolute_error' or spec.secondary_metrics:
        raise ValueError('Unsupported frozen cohort or metric; no guessed runtime adapter.')
    environment_requirements = {
        'An existing CPU execution pathway supporting the approved scalar transformations and scorer.',
        'One frozen four-row JSON list and an existing location for a complete comparison audit record.'}
    if spec.required_capabilities != ['filesystem_access'] or (len(spec.required_resources) != 1
        and set(spec.required_resources) != environment_requirements):
        raise ValueError('Demo admits the frozen JSON data and its verified local CPU environment only; preserve unsupported design.')
    return rows


from autolab.runtime.adapters import ScalarFixtureAdapter, RuntimeAdapter

class FinalDemoAdapter(ScalarFixtureAdapter):
    """Same independent scalar oracle; permit declared cohort/rule annotations."""
    adapter_id = 'final-demo-paired-scalar-v1'

    def validate_spec(self, spec, plan):
        supported_spec(spec)
        RuntimeAdapter.validate_spec(self,spec,plan)
        if set(plan.metrics) != {'mean_absolute_error'}:
            raise ValueError('Unsupported demo metric binding.')

    def dataset(self, resources):
        matches={key:rows for key,rows in resources.items() if isinstance(rows,list) and rows in COHORTS.values()}
        if len(matches)!=1:
            raise ValueError('Exactly one admitted frozen scalar dataset required.')
        return matches

    def observation_limit(self, resources):
        return super().observation_limit(self.dataset(resources))

    def metric_jobs(self, observations, resources, implementation_plan):
        jobs=super().metric_jobs(observations,self.dataset(resources),implementation_plan)
        for job in jobs:
            job.support['metric_direction']='lower'
        return jobs


def test_contract(spec, snapshot):
    rows = supported_spec(spec)
    pins = current_manifest(snapshot).resources
    resources={p.resource_id:json.loads(Path(p.path).read_text()) for p in pins}
    datasets=[p for p in pins if resources[p.resource_id] == rows]
    if len(datasets) != 1:
        raise ValueError('Prepared resource differs from the preregistered frozen cohort.')
    pin = datasets[0]
    probes = [
        Probe(component='experiment.py:compute_mae', args=[[1., 2., 3.], [1., 4., 3.]], expected=2/3, requirement='Full-denominator primary metric'),
        Probe(component='experiment.py:compute_mae', args=[[], []], raises='ValueError', requirement='Empty denominator rejected'),
        Probe(component='experiment.py:compute_mae', args=[[1.], [1., 2.]], raises='ValueError', requirement='Missing inputs cannot be zipped away'),
        Probe(component='experiment.py:compute_mae', args=[[True], [1.]], raises='ValueError', requirement='Boolean not a numeric measurement'),
        Probe(component='experiment.py:validate_samples', args=[[{'sample_id':'x', 'prediction':1.}]], raises='ValueError', requirement='Missing scoring target rejected'),
        Probe(component='experiment.py:validate_samples', args=[[{'sample_id':'x','prediction':.2,'target':.1}]*2], raises='ValueError', requirement='Duplicate identities rejected'),
        Probe(component='experiment.py:predict', args=[1.2,'baseline',1], expected={'prediction':1.2,'calls':1}, requirement='Identity control with one counted rule call'),
        Probe(component='experiment.py:predict', args=[1.2,'clipped',1], expected={'prediction':1.,'calls':1}, requirement='Upper clipping bound'),
        Probe(component='experiment.py:predict', args=[-.2,'clipped',1], expected={'prediction':0.,'calls':1}, requirement='Lower clipping bound'),
        Probe(component='experiment.py:predict', args=[.2,'baseline',0], raises='RuntimeError', requirement='Exhausted budget raises'),
        Probe(component='experiment.py:predict', args=[.2,'unknown',1], raises='ValueError', requirement='Unknown conditions rejected'),
    ]
    # Independent probes include target-domain violations; no assumption of benefit.
    from random import Random
    rng = Random(731)
    for n in (1, 2, 5, 9, 13):
        predictions = [rng.uniform(-2, 2) for _ in range(n)]
        targets = [rng.uniform(-1, 2) for _ in range(n)]
        probes.append(Probe(component='experiment.py:compute_mae', args=[predictions, targets],
            expected=sum(abs(p-t) for p,t in zip(predictions, targets))/n,
            requirement='Independent varied targets and denominators'))
    return TestContract(spec_fingerprint=spec_fingerprint(spec), probes=probes,
        required_components=['experiment.py:compute_mae','experiment.py:predict','experiment.py:validate_samples','experiment.py:Experiment.setup'],
        metric_requirements={'mean_absolute_error':'experiment.py:compute_mae'}, expected_seeds=[19],
        setup_context={'experiment_id':spec.experiment_id,'experiment_version':spec.version,'seed':19,'resource_hashes':{p.resource_id:p.checksum for p in pins}},
        fixture_resources=resources, expected_setup={'sample_count':4,'seed':19},
        provenance='Operator-owned final-demo scalar contract; independent of generated source and tests; same validated restricted runtime profile')


def operator_catalog(root, spec):
    """After approval, serialize already frozen inputs and measured CPU facts.

    These are operator-provided inputs, not readiness certification, subject
    model outputs, or measured experiment results. Preparation still registers
    resources and an independent Auditor checks suitability.
    """
    import hashlib
    import subprocess
    import sys
    rows=supported_spec(spec)
    root=Path(root)
    inputs=root/'operator-inputs'
    inputs.mkdir(exist_ok=True)
    probe=subprocess.run([sys.executable,'-I','-S','-c',
        'import sys; assert sum([1,2,3]) == 6; print(sys.version.split()[0])'],
        capture_output=True,text=True,timeout=5,check=True)
    environment={'python_version':probe.stdout.strip(),'cpu_probe_exit_status':probe.returncode,
        'runtime_profile':'Existing restricted offline Python worker; not an OS sandbox',
        'runtime_source_sha256':hashlib.sha256((PROJECT_ROOT/'src/autolab/runtime/worker.py').read_bytes()).hexdigest(),
        'implementation_worker_sha256':hashlib.sha256((PROJECT_ROOT/'src/autolab/implementation/worker.py').read_bytes()).hexdigest(),
        'scientific_result':'NONE; environment/input availability only',
        'audit_output_location':'Service-assigned immutable experiment/run directory under this isolated demo root'}
    catalog=[]
    for name,data,description in [('frozen_rows.json',rows,'Exact preregistered frozen_rows; no sampling, generation or outcome selection'),
        ('cpu_environment.json',environment,'Observed installed CPU Python path/profile and framework source hashes; code audit and readiness remain separate')]:
        path=inputs/name
        payload=json.dumps(data,sort_keys=True,indent=2)+'\n'
        if path.exists() and path.read_text()!=payload:
            raise ValueError('Operator catalog input changed; preserve old state and reconcile explicitly.')
        if not path.exists():
            path.write_text(payload)
        catalog.append({'path':str(path.resolve()),'description':description,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'data':data})
    return catalog


def recovery_facts(root,spec):
    """Observed framework/storage facts, never readiness or experiment results."""
    import os,hashlib,sys
    root=Path(root).resolve();supported_spec(spec)
    existing=root/'experiments'/spec.experiment_id/f'v{spec.version}'
    return {'scope':'Pre-implementation facts only; generated code isolation/fidelity still requires independent Code Audit and deterministic tests.',
        'existing_experiment_storage':{'path':str(existing),'exists':existing.is_dir(),'read_write_access':os.access(existing,os.R_OK|os.W_OK),
            'runtime_allocation_contract':'ExperimentRuntime creates <root>/experiments/<EXP>/runs/<RUN> with exist_ok=False only after exact run authorization; no run ID allocated yet'},
        'installed_framework_sha256':{name:hashlib.sha256((PROJECT_ROOT/name).read_bytes()).hexdigest() for name in (
            'src/autolab/runtime/service.py','src/autolab/runtime/worker.py','src/autolab/runtime/adapters.py',
            'src/autolab/implementation/worker.py','src/autolab/implementation/validation.py','src/autolab/final_demo.py','src/autolab/analysis/result_summary.py')},
        'python_version':sys.version.split()[0],
        'admitted_prediction_interface':{'component':'experiment.py:predict','arguments':['prediction','condition','budget'],
            'no_target_argument':True,'enforcement':'Operator-owned independent test contract probes this function; Code Auditor must verify no scorer state or target-derived globals access. No generated source exists yet.'},
        'visibility_contract':'The original four-row source remains unchanged for scoring. A lossless target-free projection provides prediction inputs. No new predictions, targets, samples, conditions or scoring rule are introduced.',
        'runtime_contract':{'seed':19,'conditions':['baseline','clipped'],'observations':8,'scorer_denominator_per_condition':4,
            'adapter':'FinalDemoAdapter; rejects missing, duplicate, altered or misordered rows, wrong transformed predictions, wrong targets and call counts. This describes installed validation, not measured observations.'},
        'evaluation_contract':{'hypothesis_direction':spec.success_criteria['comparison'],'falsification':spec.falsification_criteria['comparison'],
            'metric_desirability':'Lower MAE is better prediction; higher MAE can support the selected harm hypothesis. Exact numeric references are prospective deductions.'},
        'limits':'40 total transport attempts and charter/approval time gates. Actual provider dollars UNKNOWN; no provider-enforced dollar cap is claimed. Human explicitly acknowledges unknown billing.'}


class RecoveryResourceValidator:
    def __init__(self,root):self.root=Path(root)
    def validate_collection(self,snapshot,manifest,evidence):
        from autolab.orchestration.state_machine import selected_experiment
        spec=selected_experiment(snapshot);rows=supported_spec(spec)
        records={r.resource_id:r for r in snapshot.resources}
        frozen=[];projections=[]
        for pin in manifest.resources:
            data=json.loads(Path(pin.path).read_text());record=records[pin.resource_id]
            if isinstance(data,list) and data==rows:frozen.append(pin)
            if isinstance(data,list) and data==[{k:r[k] for k in ('sample_id','prediction')} for r in rows]:projections.append(pin)
        anchor=records[manifest.resources[0].resource_id]
        evidence.add(anchor,'exact_frozen_contract',len(frozen)==1,'All four ordered frozen rows, keys and values independently match the approved spec','scientific')
        evidence.add(anchor,'prediction_projection',len(projections)==1,'Exactly one lossless target-free projection; target isolation in generated code remains a later mandatory code-audit gate','scientific')
        facts=recovery_facts(self.root,spec)
        storage=facts['existing_experiment_storage']
        evidence.add(anchor,'existing_audit_storage',storage['exists'] and storage['read_write_access'],'Observed existing experiment directory access; future run allocation remains service-owned','resource')
        evidence.summaries.append({'resource_id':anchor.resource_id,'kind':'configuration','sample':facts})
