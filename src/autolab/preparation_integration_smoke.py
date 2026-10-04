"""Bounded real Omnigent preparation in separate immutable fixture databases."""
import argparse
import asyncio
from pathlib import Path
from uuid import uuid4
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.feasibility_smoke_helpers import seed_selected, explicit_test_planning
from autolab.feasibility.service import FeasibilityService
from autolab.feasibility.approval import ApprovalService
from autolab.preparation.service import PreparationService
from autolab.preparation.manifest import current_manifest, current_plan, manifest_errors
from autolab.preparation_smoke_helpers import seed_protocol, renew_protocol_approval, save_phase8, check_no_execution
from autolab.orchestration.snapshot import load_snapshot


async def smoke(*, actual_spec_only=False, include_actual=True):
    root=PROJECT_ROOT/'results'/'phase8-artifacts'/uuid4().hex
    root.mkdir(parents=True)
    actual_result=None
    if include_actual:
        with ResearchLedger(root/'actual.db') as ledger:
            project,spec,source=seed_selected(ledger)
            registry,inputs=explicit_test_planning(spec)
            FeasibilityService(ledger,registry).assess(project.project_id,spec.experiment_id,inputs)
            a=ApprovalService(ledger,allow_test_human=True); packet=a.request_approval(project.project_id,spec.experiment_id)
            a.record_human_decision(project.project_id,spec.experiment_id,spec.version,'APPROVE',packet_id=packet.packet_id,
                actor='test-human',note='Exact saved spec, no scope redesign; gaps must BLOCK',max_cost_usd=3,max_runtime_minutes=30)
            actual_result=await PreparationService(ledger,registry=registry,root=root/'actual').prepare(project.project_id)
            snapshot=load_snapshot(ledger,project.project_id); check_no_execution(snapshot)
            assert ledger.get_experiment(spec.experiment_id)==spec
            if actual_result.status not in ('BLOCK','NEEDS_USER_INPUT','NEEDS_REAPPROVAL'):
                raise RuntimeError('Saved spec was unexpectedly prepared despite absent existing resource catalog; inspect manually')
            save_phase8('phase8-actual-spec-preparation-smoke.json',ledger,project.project_id,
                result=actual_result.model_dump(mode='json'),scientific_input=source,database_path=str(root/'actual.db'))
            print(f'Actual saved {spec.experiment_id} v{spec.version}: {actual_result.status}; scientific contract unchanged')
            print(actual_result.summary)
    if actual_spec_only: return
    db=root/'protocol.db'
    with ResearchLedger(db) as ledger:
        project,spec,registry=seed_protocol(ledger)
        service=PreparationService(ledger,registry=registry,root=root/'protocol')
        result=await service.prepare(project.project_id)
        if result.status=='NEEDS_REAPPROVAL':
            plan=current_plan(load_snapshot(ledger,project.project_id))
            renew_protocol_approval(ledger,project,spec,registry,plan)
            result=await service.prepare(project.project_id)
            print('Discovered risks reviewed in fresh feasibility; explicit isolated test-human reapproval recorded')
        snapshot=load_snapshot(ledger,project.project_id); manifest=current_manifest(snapshot)
        if result.status!='PREPARED' or not manifest: raise RuntimeError(f'Protocol preparation legitimately did not complete: {result.summary}')
        assert not manifest_errors(snapshot,manifest)
        assert all(r.checksum and r.metadata.get('spec_fingerprint') and r.metadata.get('creation_tool') for r in snapshot.resources)
        output,_=save_phase8('phase8-preparation-smoke.json',ledger,project.project_id,result=result.model_dump(mode='json'),
            database_path=str(db),fixture_scope='Separate protocol fixture, not a revision or readiness certification of saved EXP_0001',
            actual_spec_result=actual_result.model_dump(mode='json') if actual_result else None)
        print('AUTOLAB_PREPARATION_OK')
        print(f'Experiment: {spec.experiment_id} v{spec.version} (isolated protocol fixture)')
        print(f'Preparation plan: {result.plan_id}; resources: {len(result.resource_ids)}')
        print(f'Manifest: {manifest.manifest_path}')
        print('All provenance present: yes; checksums: yes')
        print('Experiment code generated: no; experiment executed: no')
        print(f'Scientific output: {output}')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actual-spec-only',action='store_true')
    parser.add_argument('--protocol-only',action='store_true')
    args=parser.parse_args(); asyncio.run(smoke(actual_spec_only=args.actual_spec_only,include_actual=not args.protocol_only))
