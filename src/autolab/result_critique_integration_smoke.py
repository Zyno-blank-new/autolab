"""Independent real Critic, one optional Analyst revision, optional one PI route."""
import argparse
import asyncio
from autolab import schemas as s
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.analysis.service import AnalysisService
from autolab.analysis.persistence import reviewed_analysis
from autolab.analysis_smoke_helpers import fixture, PROJECT, save
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.budget import calculate_budget
from autolab.orchestration.state_machine import derive_control_state
from autolab.orchestration.models import RoutingDecision
from autolab.planner.service import OmnigentPlanner

async def smoke(planner=False):
    configure();info=fixture()
    with ResearchLedger(info['database_path']) as ledger:
        workflow=AnalysisService(ledger)
        # Explicit fixture-human gate decision, never falsely attributed to PI.
        snap=load_snapshot(ledger,PROJECT)
        decision=s.NextDecision(decision_id=ledger.next_id('DEC'),project_id=PROJECT,action='ANALYZE_RESULT',target_agent='critic',
            reason='Explicit Phase 11 isolated critique of persisted actual analysis',remaining_budget_usd=calculate_budget(snap).remaining_budget_usd)
        ledger.add_decision(decision)
        orch=Orchestrator(ledger,OmnigentPlanner())
        route=RoutingDecision(decision_id=decision.decision_id,action=decision.action,target_role='critic',reason=decision.reason,context_requirements=decision.required_context_ids,
            control_state=derive_control_state(load_snapshot(ledger,PROJECT)))
        result=await orch.execute_analysis(route,workflow)
        planner_route=None
        if planner and reviewed_analysis(load_snapshot(ledger,PROJECT)):
            # At most one actual PI call; an illegal output is preserved as a failure,
            # not repaired with another paid call or forced action.
            planner_route=await orch.decide(PROJECT,max_repairs=0)
        artifact=save('phase11-result-critique-smoke.json',ledger,{'result':result.model_dump(mode='json'),
            'model_calls':{'analyst':workflow.agent.calls,'critic':workflow.critic.calls,'planner':orch.planner.calls},
            'planner_route':planner_route.model_dump(mode='json') if planner_route else None,'phase12_executed':False})
        print('AUTOLAB_RESULT_CRITIQUE_OK')
        print('Analysis:',result.analysis_id,'v'+str(result.version),'Critic:',result.verdict)
        print('Revision rounds:',result.revision_rounds,'Reviewed: yes','Phase 12 executed: no')
        print('Artifact:',artifact)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--planner',action='store_true');args=parser.parse_args()
    asyncio.run(smoke(args.planner))
