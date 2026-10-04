"""Explicitly isolated Phase 9 AI prediction protocol; never a scientific run."""
import hashlib
import json
from pathlib import Path
from random import Random
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.feasibility.approval import ApprovalService
from autolab.feasibility.capability_registry import CapabilityRegistry
from autolab.feasibility.models import Capability, FeasibilityInputs, CostInput, EstimateRange, ResourceAccess
from autolab.feasibility.service import FeasibilityService
from autolab.feasibility.persistence import spec_fingerprint
from autolab.orchestration.models import ProjectSnapshot, ApprovalScope
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import readiness_passes, approval_for
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.preparation.models import AcceptanceCriteria, ResourceRequirement, ResourcePreparationPlan
from autolab.preparation.service import PreparationService
from autolab.preparation.manifest import current_manifest
from autolab.readiness.service import ReadinessService
from autolab.implementation.models import TestContract, Probe

PROJECT = 'PROJECT_PHASE9_ISOLATED'


def assert_no_execution(snapshot):
    if snapshot.runs or snapshot.metrics or snapshot.analyses:
        raise RuntimeError('Phase 9 crossed scientific execution boundary')
    if any(e.event_type in ('EXPERIMENT_RUN_STARTED', 'EXPERIMENT_EXECUTED') for e in snapshot.events):
        raise RuntimeError('Unexpected scientific execution event')


def decision(snapshot, action='IMPLEMENT_EXPERIMENT', target='implementer'):
    return s.NextDecision(decision_id='DEC_PHASE9_CHECK', project_id=snapshot.charter.project_id,
        action=action, target_agent=target, reason='Verify exact Phase 9 eligibility without dispatch',
        remaining_budget_usd=snapshot.charter.budget_usd)


def verify_real_blocked():
    """Read the actual saved Phase 8 state, without opening/mutating its database."""
    path = PROJECT_ROOT/'results/phase8-actual-spec-preparation-smoke.json'
    if not path.exists(): return {'available': False, 'reason': 'Actual saved Phase 8 artifact unavailable in clean checkout'}
    original = path.read_bytes(); data = json.loads(original)
    snapshot = ProjectSnapshot.model_validate(data['snapshot'])
    assert any(e.experiment_id == 'EXP_0001' for e in snapshot.experiments)
    assert data['result']['status'] == 'BLOCK'
    result = DecisionValidator().validate(decision(snapshot), snapshot)
    assert not result.valid and not snapshot.implementations
    assert path.read_bytes() == original
    return {'available': True, 'rejected': True, 'reasons': result.reasons,
        'saved_snapshot_sha256': hashlib.sha256(original).hexdigest(), 'database_path': data.get('database_path')}


async def seed_fixture(ledger, root, *, project_id=PROJECT, experiment_id='EXP_PHASE9', execution_fixture=False,
                       resource_rows=None, secondary_metrics=()):
    # A Phase 10 fixture creates a NEW charter/project, never edits Phase 9 history.
    fixture_project = project_id
    project = ledger.create_project(s.ResearchCharter(project_id=fixture_project, title='Isolated prediction implementation protocol',
        research_question='Can bounded clipping versus an unchanged prediction rule be faithfully implemented?',
        objective=('Execute the fixed paired protocol and preserve measurements without interpretation' if execution_fixture else 'Validate implementation mechanics only; no scientific effect or adequacy claim'),
        primary_outcome='Future condition-wise mean absolute error', budget_usd=100, max_runtime_minutes=240,
        constraints={'scope': ('Tiny offline fixed-input execution fixture; no inference, training or interpretation' if execution_fixture else 'Tiny local fixed-input implementation fixture; no inference, training or scientific run'),
            **({'parent_fixture':'PROJECT_PHASE9_ISOLATED','authorization':'Explicit Phase 10 task; new isolated execution charter'} if execution_fixture else {})}))
    hypothesis = ledger.add_hypothesis(s.Hypothesis(hypothesis_id='HYP_PHASE9', project_id=fixture_project,
        statement='Clipping a scalar AI prediction to the preregistered target range could change absolute error',
        falsifiable_prediction='Condition-wise mean absolute error can differ on the same held-out inputs'))
    spec = ledger.add_experiment_spec(s.ExperimentSpec(experiment_id=experiment_id, project_id=fixture_project,
        hypothesis_id=hypothesis.hypothesis_id, title='Matched scalar prediction rule fixture',
        objective='Implement baseline identity and intervention clipping on every frozen held-out prediction using one counted operation per sample per condition',
        experiment_type='local computational AI prediction protocol fixture',
        independent_variables={'condition': ['baseline', 'clipped'], 'seed': 19, 'max_calls_per_sample': 1},
        dependent_variables={'absolute_error': 'abs(prediction - target)'},
        controls={'baseline': 'prediction unchanged', 'intervention': 'min(1.0,max(0.0,prediction))',
            'pairing': 'Every fixed sample in both conditions, same input order, fresh per-sample budget',
            'leakage': 'Rule receives prediction only; target is available only to scorer, no training/tuning',
            'budget': 'One attempted rule invocation counts even on error; exhausted budget raises, missing/invalid samples never skipped'},
        dataset_requirements={'min_samples': 4, 'fields': ['sample_id','prediction','target'], 'selection': 'All four fixed held-out rows, no exclusions'},
        required_resources=['Frozen held-out scalar predictions and scoring references'], required_capabilities=['filesystem_access'],
        primary_metric='mean_absolute_error', secondary_metrics=list(secondary_metrics),
        success_criteria={'definition': 'Future clipped MAE below baseline; fixture has no inferential claim'},
        falsification_criteria={'definition': 'Future clipped MAE at or above baseline'},
        assumptions=['Targets constrained to [0,1]; finite numeric input; no external inference'],
        potential_confounders=['Small fixture cannot establish generalization'], estimated_cost_usd=0, estimated_runtime_minutes=1))
    ledger.add_review(s.ReviewRecord(review_id='REV_PHASE9_SPEC', project_id=fixture_project, review_type='experiment',
        target_type='experiments', target_id=spec.experiment_id, verdict='PASS', reviewer_role='critic',
        recommendations=['Explicit test-only scientific contract; no scientific execution or production approval']))
    registry = CapabilityRegistry([Capability(capability_id='filesystem_access', status='AVAILABLE', provider='Local tiny fixture')])
    inputs = FeasibilityInputs(resource_access=[ResourceAccess(requirement=spec.required_resources[0], status='AVAILABLE')],
        costs=[CostInput(category='Fixture implementation/audit pursuit cap; provider price unknown', units=EstimateRange(minimum=0, maximum=5), unit_price_usd=None)],
        runtime_minutes=EstimateRange(minimum=1, maximum=60), compute_requirements=['Local CPU'],
        warnings=['Test-only fixture, no scientific effect claim; no new dependencies'])
    FeasibilityService(ledger, registry).assess(fixture_project, spec.experiment_id, inputs)
    approval = ApprovalService(ledger, allow_test_human=True); packet = approval.request_approval(fixture_project, spec.experiment_id)
    approval.record_human_decision(fixture_project, spec.experiment_id, 1, 'APPROVE', packet_id=packet.packet_id,
        actor='test-human', max_cost_usd=10, max_runtime_minutes=60, acknowledge_unknowns=True,
        note='Explicit isolated implementation and audit mechanics only; no production experiment execution',
        approved_actions=['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT'])
    rows = resource_rows if resource_rows is not None else [{'sample_id':f'toy-{i}', 'prediction':v, 'target':t} for i,(v,t) in enumerate([(-0.2,0.1),(0.3,0.4),(1.2,0.9),(0.7,0.7)])]
    criteria = AcceptanceCriteria(required_fields=['sample_id','prediction','target'],
        field_types={'sample_id':'string','prediction':'number','target':'number'}, min_samples=4, unique_fields=['sample_id'],
        scientific=['Rule sees prediction only, references used only by scorer; all fixed inputs shared'],
        technical=['Finite numeric predictions and targets; JSON rows'], provenance=['Frozen generator specification and hash'])
    requirement = ResourceRequirement(requirement_id='predictions', spec_requirements=spec.required_resources,
        resource_type='dataset', purpose='Outcome-independent fixture prediction/scoring input', acquisition_mode='SYNTHESIZE',
        expected_output='Four fixed JSON rows', required_capabilities=['filesystem_access'], steps=['Serialize frozen toy input data'],
        criteria=criteria, handler='synthetic', parameters={'data':rows, 'seed':19, 'specification':'Fixed protocol input rows, no measured scientific results'},
        estimated_cost_usd=0, estimated_runtime_minutes=0.01)
    class Preparer:
        async def plan(self, context, assignment, **kwargs): return ResourcePreparationPlan(**assignment, resource_requirements=[requirement])
    class ReadinessFixtureAuditor:
        async def audit(self, context, assignment):
            return s.ReadinessReport(**assignment, resource_readiness=True, technical_readiness=True, scientific_readiness=True,
                quality_readiness=True, verdict='PASS', warnings=['Controlled independent fixture audit, not production resource certification'],
                metadata={'semantic_findings':[{'gate':'scientific', 'resource_ids':[p['resource_id'] for p in context['resource_pins']],
                    'finding':'Frozen paired scalar inputs fit this exact protocol; target is scorer-only', 'evidence':'Explicit four-row fixture contract'}]})
    await PreparationService(ledger, Preparer(), registry=registry, root=root).prepare(fixture_project)
    await ReadinessService(ledger, ReadinessFixtureAuditor()).audit(fixture_project)
    snapshot = load_snapshot(ledger, fixture_project); assert readiness_passes(snapshot)
    manifest = current_manifest(snapshot); pin = manifest.resources[0]
    probes = [Probe(component='experiment.py:compute_mae', args=[[1.,2.,3.],[1.,4.,3.]], expected=2/3, requirement='primary_metric: total error / all samples'),
        Probe(component='experiment.py:compute_mae', args=[[],[]], raises='ValueError', requirement='No empty denominator'),
        Probe(component='experiment.py:compute_mae', args=[[1.],[1.,2.]], raises='ValueError', requirement='Missing samples must not be silently zipped/skipped'),
        Probe(component='experiment.py:compute_mae', args=[[True],[1.]], raises='ValueError', requirement='Boolean is not numeric sample'),
        Probe(component='experiment.py:validate_samples', args=[[{'sample_id':'x','prediction':1.}]], raises='ValueError', requirement='Missing target never silently skipped'),
        Probe(component='experiment.py:validate_samples', args=[[{'sample_id':'x','prediction':0.2,'target':0.1}]*2], raises='ValueError', requirement='Duplicate sample identity rejected'),
        Probe(component='experiment.py:predict', args=[1.2,'baseline',1], expected={'prediction':1.2,'calls':1}, requirement='Identity control, one counted call'),
        Probe(component='experiment.py:predict', args=[1.2,'clipped',1], expected={'prediction':1.,'calls':1}, requirement='Clipped intervention, matched single call'),
        Probe(component='experiment.py:predict', args=[-0.2,'clipped',1], expected={'prediction':0.,'calls':1}, requirement='Lower clipping bound'),
        Probe(component='experiment.py:predict', args=[0.2,'baseline',0], raises='RuntimeError', requirement='Budget exhausted before invocation'),
        Probe(component='experiment.py:predict', args=[0.2,'unknown',1], raises='ValueError', requirement='Unknown condition rejected')]
    rng = Random(731)
    for n in (1,2,5,9,13):
        pred = [rng.uniform(-2,2) for _ in range(n)]; target = [rng.random() for _ in range(n)]
        probes.append(Probe(component='experiment.py:compute_mae', args=[pred,target], expected=sum(abs(p-t) for p,t in zip(pred,target))/n,
            requirement='Independent metric oracle across varied toy denominators'))
    contract = TestContract(spec_fingerprint=spec_fingerprint(spec), probes=probes,
        required_components=['experiment.py:compute_mae','experiment.py:predict','experiment.py:validate_samples','experiment.py:Experiment.setup'],
        metric_requirements={spec.primary_metric:'experiment.py:compute_mae',
            **{name:'experiment.py:compute_error_sum' for name in secondary_metrics}}, expected_seeds=[19],
        setup_context={'experiment_id':spec.experiment_id,'experiment_version':1,'seed':19,'resource_hashes':{pin.resource_id:pin.checksum}},
        fixture_resources={pin.resource_id:rows}, expected_setup={'sample_count':4,'seed':19},
        provenance='Framework-owned preregistered scalar-fixture adapter; independent of Implementer-generated code/tests')
    assert DecisionValidator().validate(decision(snapshot), snapshot).valid
    assert_no_execution(snapshot)
    return project, spec, contract


def approve_fixture_run_eligibility(ledger, record):
    """Explicit test-human future-run scope; no actual run dispatch or approval API expansion."""
    snapshot = load_snapshot(ledger, record.project_id)
    prior = approval_for(snapshot, s.PlannerAction.IMPLEMENT_EXPERIMENT)
    if not prior: raise RuntimeError('Fixture implementation approval stale')
    scope = ApprovalScope.model_validate({**prior.model_dump(mode='json'),
        'approved_actions':['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT','RUN_EXPERIMENT'],
        'implementation_id':record.implementation_id, 'note':'Explicit isolated test-human future-run ELIGIBILITY only; Phase 9 stops without dispatch'})
    ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'), project_id=record.project_id, event_type='HUMAN_APPROVED',
        actor='test-human', target_type='experiments', target_id=record.experiment_id,
        summary='Fixture-only exact implementation future-run scope; no scientific execution', payload=scope.model_dump(mode='json')))
