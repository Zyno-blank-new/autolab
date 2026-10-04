"""Real independent Omnigent readiness; optional one adaptive Planner boundary."""
import argparse
import asyncio
import json
from pathlib import Path
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.readiness.service import ReadinessService
from autolab.preparation.service import PreparationService
from autolab.preparation.manifest import current_plan, current_manifest, manifest_errors
from autolab.preparation_smoke_helpers import save_phase8, check_no_execution, ProtocolFixtureValidator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import readiness_passes
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.orchestrator import Orchestrator
from autolab.planner.service import OmnigentPlanner


class OneCallPlanner(OmnigentPlanner):
    async def propose(self,*args,**kwargs):
        if self.calls: raise RuntimeError('Smoke allows one Planner call only; no paid repair call')
        return await super().propose(*args,**kwargs)


async def smoke(*, with_planner=False):
    preparation=json.loads((PROJECT_ROOT/'results/phase8-preparation-smoke.json').read_text())
    with ResearchLedger(preparation['database_path']) as ledger:
        project_id=preparation['snapshot']['charter']['project_id']
        auditor=ReadinessService(ledger)
        auditor.validators.register(ProtocolFixtureValidator())
        report=await auditor.audit(project_id)
        repairs=0
        while report.verdict=='REPAIR' and repairs<2:
            snap=load_snapshot(ledger,project_id); plan=current_plan(snap)
            service=PreparationService(ledger,root=Path(current_manifest(snap).manifest_path).parents[3])
            result=await service.prepare(project_id,previous=plan,issues=report.metadata['issues'])
            if result.status!='PREPARED': break
            repairs+=1; report=await auditor.audit(project_id)
        if report.verdict=='REPAIR' and repairs==2: report=auditor.record_exhausted(project_id,report)
        snapshot=load_snapshot(ledger,project_id); check_no_execution(snapshot)
        manifest=current_manifest(snapshot)
        assert report.metadata['deterministic_findings'] and report.metadata['semantic_findings']
        deterministic=all(f['passed'] for f in report.metadata['deterministic_findings'])
        eligible=s.PlannerAction.IMPLEMENT_EXPERIMENT in DecisionValidator().legal_actions(snapshot)
        route=None
        if report.verdict=='PASS':
            assert readiness_passes(snapshot) and not manifest_errors(snapshot,manifest) and eligible
            if with_planner: route=await Orchestrator(ledger,OneCallPlanner(timeout_seconds=360)).decide(project_id)
        output,_=save_phase8('phase8-readiness-smoke.json',ledger,project_id,report=report.model_dump(mode='json'),
            deterministic_pass=deterministic,implementation_eligible=eligible,repair_attempts=repairs,
            planner_route=route.model_dump(mode='json') if route else None,
            planner_context=ContextBuilder().build(load_snapshot(ledger,project_id)).model_dump(mode='json'),database_path=preparation['database_path'])
        if report.verdict!='PASS':
            print(f'Readiness honest outcome: {report.verdict.value}; {report.failed_checks}; implementation remains gated')
            raise SystemExit(1)
        print('AUTOLAB_READINESS_OK')
        print(f'Experiment: {report.experiment_id}; resources: {len(manifest.resources)} (protocol fixture only)')
        print(f'Deterministic checks: {"PASS" if deterministic else "FAIL"}; semantic audit: PASS; readiness: PASS')
        print(f'Implementation eligible: {"yes" if eligible else "no"}; implementation executed: no')
        print(f'Repair attempts: {repairs}; output: {output}')
        if route: print(f'Planner: {route.action.value} → {route.target_role}; returned routing boundary only')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--with-planner',action='store_true')
    asyncio.run(smoke(with_planner=parser.parse_args().with_planner))
