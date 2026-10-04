"""Execute a new, explicitly authorized offline fixture; never dispatch analysis."""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.orchestration.budget import calculate_budget
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.planner.service import OmnigentPlanner
from autolab.runtime.service import ExperimentRuntime
from autolab.runtime.persistence import valid_result
from autolab.runtime_smoke_helpers import PROJECT,prepare_live_fixture,repair_fixture_binding,verify_real_run_blocked


async def smoke(*,planner=False,prepared=None,repair_preparation=None):
    # --prepared resumes an already separately audited fixture without another
    # audit/model call. It refuses to rerun a completed smoke or completed charter.
    if repair_preparation:
        root=Path(repair_preparation).resolve();db=root/'fixture.db'
    elif prepared:
        saved=json.loads(Path(prepared).read_text()); root=Path(saved['root']); db=saved['database_path']
    else:
        root=PROJECT_ROOT/'results/phase10-artifacts'/uuid4().hex; root.mkdir(parents=True)
        db=root/'fixture.db'
    with ResearchLedger(db) as ledger:
        if repair_preparation:
            _,spec,record,adapter=await repair_fixture_binding(ledger,root)
            (PROJECT_ROOT/'results/phase10-prepared-fixture.json').write_text(json.dumps({'root':str(root),'database_path':str(db)},indent=2))
        elif prepared:
            from autolab.runtime.adapters import ScalarFixtureAdapter
            from autolab.feasibility.persistence import spec_fingerprint
            from autolab.orchestration.state_machine import selected_experiment
            snapshot=load_snapshot(ledger,PROJECT);spec=selected_experiment(snapshot)
            if snapshot.runs: raise RuntimeError('Prepared smoke already executed; create a fresh isolated attempt explicitly')
            adapter=ScalarFixtureAdapter(spec_fingerprint(spec))
        else:
            _,spec,record,adapter=await prepare_live_fixture(ledger,root)
            (PROJECT_ROOT/'results/phase10-prepared-fixture.json').write_text(json.dumps({'root':str(root),'database_path':str(db)},indent=2))
        runtime=ExperimentRuntime(ledger,root=root,adapters={adapter.spec_hash:adapter})
        snapshot=load_snapshot(ledger,PROJECT)
        proposal=s.NextDecision(decision_id=ledger.next_id('DEC'),project_id=PROJECT,action='RUN_EXPERIMENT',
            target_agent='experiment_runner',reason='Explicit isolated Phase 10 execution smoke; offline fixed scientific contract',
            remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd)
        assert DecisionValidator().validate(proposal,snapshot).valid
        # The fixture supplies an explicit persisted legal decision. A real PI
        # may choose its own next action via the same dispatch interface.
        ledger.add_decision(proposal)
        from autolab.orchestration.models import RoutingDecision
        route=RoutingDecision(decision_id=proposal.decision_id,action=proposal.action,target_role=proposal.target_agent,
            reason=proposal.reason,context_requirements=[],control_state='READY_TO_RUN')
        runner=Orchestrator(ledger,OmnigentPlanner())
        first=await runner.execute_runtime(route,runtime)
        if first.status!='COMPLETED': raise RuntimeError('Fixture execution failed; inspect preserved artifacts')
        second=await runtime.run(PROJECT)
        if second.status!='COMPLETED': raise RuntimeError('Reproducibility attempt failed; preserve both runs')
        snapshot=load_snapshot(ledger,PROJECT)
        assert valid_result(snapshot,first) and valid_result(snapshot,second)
        def observations(record):
            return [json.loads(line)['observation'] for line in Path(record.output_manifest['artifacts']['raw_outputs.jsonl']['path']).read_text().splitlines()]
        assert first.run_id!=second.run_id and observations(first)==observations(second)
        metrics=lambda identifier:[(m.metric_name,m.metadata['condition'],m.metric_value,m.metadata['denominator']) for m in snapshot.metrics if m.run_id==identifier]
        assert metrics(first.run_id)==metrics(second.run_id)
        for metric in snapshot.metrics:
            source=first if metric.run_id==first.run_id else second
            group=[o for o in observations(source) if o['condition']==metric.metadata['condition']]
            expected=sum(abs(o['outputs']['prediction']-o['outputs']['target']) for o in group)/len(group)
            import math
            assert math.isclose(metric.metric_value,expected,rel_tol=1e-12,abs_tol=1e-12)
        assert 'ANALYZE_RESULT' in DecisionValidator().legal_actions(snapshot)
        next_route=await runner.decide(PROJECT) if planner else None
        snapshot=load_snapshot(ledger,PROJECT)
        assert not snapshot.analyses
        blocked=verify_real_run_blocked();assert blocked.get('rejected')
        output={'root':str(root),'database_path':str(db),'runs':[first.model_dump(mode='json'),second.model_dump(mode='json')],
            'snapshot':snapshot.model_dump(mode='json'),'metric_integrity':'PASS','reproducibility':'PASS',
            'real_blocked':blocked,'planner_route':next_route.model_dump(mode='json') if next_route else None,
            'scientific_interpretation_performed':False,'analysis_executed':False}
        (PROJECT_ROOT/'results/phase10-runtime-smoke.json').write_text(json.dumps(output,indent=2,allow_nan=False))
        print('AUTOLAB_EXPERIMENT_RUN_OK')
        print('Experiment: '+spec.experiment_id+' v'+str(spec.version))
        print('Runs: '+first.run_id+', '+second.run_id+'; status: COMPLETED')
        print('Raw observations per run: '+str(first.output_manifest['observation_count']))
        print('Preregistered metrics: '+json.dumps(metrics(first.run_id)))
        print('Artifact hashes: verified; independent metric recomputation: PASS; reproducibility: PASS')
        if next_route: print('Post-run Planner: '+next_route.action.value+'; legal: yes; route boundary only')
        print('Scientific interpretation performed: no; Analysis Agent executed: no')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--planner',action='store_true',help='At most one real Omnigent Planner call; route only')
    parser.add_argument('--prepared',help='Resume the saved separately audited, unexecuted Phase 10 fixture')
    parser.add_argument('--repair-preparation',help='Bounded independent reassessment of a blocked fixture identity import; never runtime auto-repair')
    args=parser.parse_args();asyncio.run(smoke(planner=args.planner,prepared=args.prepared,repair_preparation=args.repair_preparation))
