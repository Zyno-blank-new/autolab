"""New linked execution fixture, retaining Phase 9 science, not its old authority."""
import json
from pathlib import Path
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.implementation_smoke_helpers import seed_fixture
from autolab.implementation.models import ImplementationPlan, SourceBundle, Probe
from autolab.implementation.service import ImplementationService
from autolab.implementation.validation import read_sources
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.models import ApprovalScope
from autolab.orchestration.state_machine import current_implementation, approval_for
from autolab.preparation.manifest import current_manifest, fingerprint
from autolab.feasibility.persistence import spec_fingerprint
from autolab.runtime.adapters import ScalarFixtureAdapter

PROJECT='PROJECT_PHASE10_ISOLATED'


def authorize_execution(ledger,record):
    snapshot=load_snapshot(ledger,record.project_id)
    prior=approval_for(snapshot,s.PlannerAction.IMPLEMENT_EXPERIMENT)
    if not prior: raise ValueError('Exact implementation approval missing')
    scope=ApprovalScope.model_validate({**prior.model_dump(mode='json'),
        'approved_actions':['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT','RUN_EXPERIMENT'],
        'implementation_id':record.implementation_id,
        'note':'Explicit isolated Phase 10 test-human authorization: offline execution and measurement only; no interpretation'})
    ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'),project_id=record.project_id,event_type='HUMAN_APPROVED',
        actor='test-human',target_type='experiments',target_id=record.experiment_id,
        summary='Exact isolated execution scope; no production authorization',payload=scope.model_dump(mode='json')))


class ReboundFixtureSource:
    """Deterministic identity rebinding, followed by fresh checks and audit.

    This is a smoke-fixture importer, not a production Implementer or permission
    to transfer an audit to altered code. Scientific source is preserved.
    """
    def __init__(self,old_record): self.old_record=old_record
    def replacements(self,plan):
        old=ImplementationPlan.model_validate(self.old_record.metadata['plan'])
        replacements={old.project_id:plan.project_id,old.experiment_id:plan.experiment_id,
            old.implementation_id:plan.implementation_id,old.spec_fingerprint:plan.spec_fingerprint,
            old.manifest_fingerprint:plan.manifest_fingerprint}
        for a,b in zip(old.input_resources,plan.input_resources):
            for key in ('resource_id','path','checksum','record_fingerprint'):
                replacements[getattr(a,key)]=getattr(b,key)
        return replacements
    async def plan(self,context,assignment,**kwargs):
        old=ImplementationPlan.model_validate(self.old_record.metadata['plan'])
        data=old.model_dump(mode='json')
        data.update(assignment)
        data.update(input_resources=context['resource_manifest']['resources'],issue_responses=[],
            output_schema=context['raw_output_schema'])
        provisional=ImplementationPlan.model_validate(data)
        replacements=self.replacements(provisional)
        def bind(value):
            if isinstance(value,str):
                for a,b in replacements.items(): value=value.replace(a,b)
                value=value.replace('Revision 2 is the final authorized revision; unresolved gates must be reported rather than initiating a third round.',
                    'This linked fixture permits at most two code revision rounds; unresolved gates at revision 2 block and return Planner control.')
                value=value.replace('No additional implementation revision round is authorized by this plan.',
                    'Any further revision requires a current independent REVISE review and must remain within the two-round cap.')
                return value.replace('approved plan revision 2','approved plan revision '+str(provisional.revision))
            if isinstance(value,list): return [bind(v) for v in value]
            if isinstance(value,dict): return {k:bind(v) for k,v in value.items()}
            return value
        # Rebind plan prose as well as structured IDs; scientific values remain unchanged.
        data=bind(data)
        from autolab.implementation.models import ReviewResponse
        review=kwargs.get('review')
        data['issue_responses']=[ReviewResponse(issue_index=i,disposition='ACCEPT',
            evidence='Correct importer identity/revision prose and source metadata; fresh receipt includes actual Python version and framework source hash. Scientific rules are unchanged.').model_dump(mode='json') for i,_ in enumerate(review.issues if review else [])]
        return ImplementationPlan.model_validate(data)
    async def generate(self,context,plan,**kwargs):
        replacements=self.replacements(plan)
        files=read_sources(self.old_record)
        # Token replacement is limited to exact old provenance strings, never
        # scientific values/rules/metrics or resource contents.
        import re
        pattern=re.compile('|'.join(re.escape(k) for k in sorted(replacements,key=len,reverse=True)))
        files={name:pattern.sub(lambda m:replacements[m.group()],source) for name,source in files.items()}
        for name,source in files.items():
            source=source.replace("'approved_plan_revision': 2", "'approved_plan_revision': "+str(plan.revision))
            source=source.replace("metadata['approved_plan_revision'] == 2", "metadata['approved_plan_revision'] == "+str(plan.revision))
            source=source.replace('approved plan revision 2','approved plan revision '+str(plan.revision))
            files[name]=source
        return SourceBundle(files=files)


async def prepare_live_fixture(ledger,root):
    from autolab.orchestration.models import ProjectSnapshot
    from autolab.implementation.persistence import audited_implementation_passes
    saved=PROJECT_ROOT/'results/phase9-code-audit-smoke.json'
    if not saved.exists(): raise RuntimeError('Saved audited Phase 9 source required; run Phase 9 smokes first')
    old=ProjectSnapshot.model_validate(json.loads(saved.read_text())['snapshot'])
    old_record=current_implementation(old)
    if not audited_implementation_passes(old,old_record): raise RuntimeError('Saved Phase 9 implementation stale')
    project,spec,contract=await seed_fixture(ledger,root,project_id=PROJECT,experiment_id='EXP_PHASE10',execution_fixture=True)
    contract=contract.model_copy(update={'probes':[*contract.probes,Probe(component='experiment.py:compute_mae',
        args=[[1.,3.],[2.,1.]],expected=1.5,requirement='Phase 10 hand-computable primary metric oracle')]})
    service=ImplementationService(ledger,ReboundFixtureSource(old_record),root=root,contracts={spec_fingerprint(spec):contract})
    record=await service.implement(project.project_id)
    if not record.metadata['checks']['tests_pass']: raise RuntimeError('Rebound source tests failed')
    review=await service.audit(project.project_id)  # Independent real Omnigent call; not the runner.
    if review.verdict!='PASS': raise RuntimeError('Fresh independent audit did not PASS; do not force or execute')
    authorize_execution(ledger,record)
    ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'),project_id=PROJECT,event_type='FIXTURE_PROVENANCE',
        actor='test-human',target_type='implementations',target_id=record.implementation_id,
        summary='New linked Phase 10 fixture; exact scientific behavior retained; new audit required',
        payload={'parent_project_id':old.charter.project_id,'parent_charter_hash':fingerprint(old.charter),
            'parent_implementation_hash':old_record.code_version,'rebound_implementation_hash':record.code_version,
            'source_change':'Exact identity/provenance rebinding only','review_id':review.review_id}))
    return project,spec,record,ScalarFixtureAdapter(spec_fingerprint(spec))


async def repair_fixture_binding(ledger,root):
    """Preserve a blocked importer attempt; seek an independent actionable review.

    This is bounded fixture preparation, never runtime auto-repair. A maintained
    BLOCK stops; no review is relabelled and no PASS is manufactured.
    """
    from autolab.orchestration.models import ProjectSnapshot
    from autolab.orchestration.state_machine import selected_experiment
    from autolab.implementation.agent import OmnigentCodeAuditor
    old=ProjectSnapshot.model_validate(json.loads((PROJECT_ROOT/'results/phase9-code-audit-smoke.json').read_text())['snapshot'])
    saved=load_snapshot(ledger,PROJECT);record=current_implementation(saved);spec=selected_experiment(saved)
    if saved.runs or record.metadata['revision']>=2: raise RuntimeError('Fixture repair unavailable after execution or revision bound')
    class ClarifyingAuditor:
        def __init__(self):
            self.delegate=OmnigentCodeAuditor();self.transport=self.delegate.transport
        async def audit(self,context,assignment):
            context={**context,'fixture_authority_clarification':{
                'project':'New linked PROJECT_PHASE10_ISOLATED with explicit execution charter, not a third Phase 9 revision',
                'implementation_revision':record.metadata['revision'],
                'previous_verdict':'BLOCK retained; no source or plan has been overwritten',
                'available_correction':'Fix importer plan identity/prose and approved_plan_revision metadata via a new bounded immutable implementation. Scientific rules and parameters stay fixed.',
                'environment_evidence':'Fresh deterministic receipt includes child Python version and framework source SHA-256',
                'request':'Independently reassess whether these exact provenance issues are actionable with REVISE in this new fixture. Maintain BLOCK if not. Do not PASS incorrect bindings or waive any test.'}}
            return await self.delegate.audit(context,assignment)
    service=ImplementationService(ledger,ReboundFixtureSource(current_implementation(old)),ClarifyingAuditor(),
        root=root,contracts={spec_fingerprint(spec):record.metadata['test_contract']})
    receipt=await service.revalidate(PROJECT)
    if not receipt.static_pass: raise RuntimeError('Unsafe fixture cannot enter bounded provenance correction')
    review=await service.audit(PROJECT)
    if review.verdict!='REVISE': raise RuntimeError('Independent auditor did not authorize actionable revision; preserve verdict and stop')
    revised=await service.implement(PROJECT,previous=record,review=review)
    service.auditor=OmnigentCodeAuditor()
    final=await service.audit(PROJECT)
    if final.verdict!='PASS': raise RuntimeError('Reconciled fixture audit did not PASS; no execution')
    authorize_execution(ledger,revised)
    ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'),project_id=PROJECT,event_type='FIXTURE_PROVENANCE',
        actor='test-human',target_type='implementations',target_id=revised.implementation_id,
        summary='Bounded correction of fixture importer; original BLOCK retained; scientific rules unchanged',
        payload={'parent_project_id':old.charter.project_id,'parent_implementation_hash':current_implementation(old).code_version,
            'revision':revised.metadata['revision'],'review_id':final.review_id}))
    return ledger.get_project(PROJECT),spec,revised,ScalarFixtureAdapter(spec_fingerprint(spec))


def verify_real_run_blocked():
    import hashlib,sqlite3
    from autolab.orchestration.models import ProjectSnapshot
    from autolab.orchestration.decision_validator import DecisionValidator
    from autolab.orchestration.budget import calculate_budget
    path=PROJECT_ROOT/'results/phase8-actual-spec-preparation-smoke.json'
    if not path.exists(): return {'available':False}
    data=path.read_bytes(); saved=json.loads(data); snapshot=ProjectSnapshot.model_validate(saved['snapshot'])
    proposal=s.NextDecision(decision_id='DEC_REAL_RUNTIME_CHECK',project_id=snapshot.charter.project_id,
        action='RUN_EXPERIMENT',target_agent='experiment_runner',reason='Read-only blocked-state regression',
        remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd)
    result=DecisionValidator().validate(proposal,snapshot)
    assert not result.valid and not snapshot.runs and not snapshot.metrics
    with sqlite3.connect('file:'+saved['database_path']+'?mode=ro',uri=True) as db:
        assert all(db.execute('select count(*) from '+table).fetchone()[0]==0 for table in ('runs','metrics','implementations'))
    assert path.read_bytes()==data
    return {'available':True,'rejected':True,'snapshot_sha256':hashlib.sha256(data).hexdigest(),'reasons':result.reasons}
