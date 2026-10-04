"""Real adaptive choice→existing design/critique→selection→human boundary.

Legal divergence is retained; no stochastic choice is replaced or forced.
"""
import asyncio
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.planner.service import OmnigentPlanner
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_experiment
from autolab.feasibility.service import FeasibilityService
from autolab.feasibility.approval import ApprovalService
from autolab.adaptive_smoke_helpers import create_fixture, save, PROJECT


async def smoke(label='adaptive-followup'):
    configure()
    info = create_fixture(label)
    with ResearchLedger(info['database_path']) as ledger:
        planner = OmnigentPlanner()
        orchestrator = Orchestrator(ledger, planner)
        route = await orchestrator.decide(PROJECT, max_repairs=0)
        divergence = route.action not in ('RUN_FOLLOWUP', 'DESIGN_EXPERIMENT')
        if divergence:
            # Terminal dispositions are practical to execute without extra calls.
            if route.action in ('STOP', 'ACCEPT_HYPOTHESIS', 'REJECT_HYPOTHESIS'):
                await orchestrator.execute_adaptive(route)
            elif route.action == 'GATHER_EVIDENCE':
                await orchestrator.execute_adaptive(route)
            result = {'status': 'LEGAL_DIVERGENCE', 'chosen_action': route.action.value,
                      'executed': route.action in ('STOP', 'ACCEPT_HYPOTHESIS', 'REJECT_HYPOTHESIS', 'GATHER_EVIDENCE')}
            if label == 'adaptive-loop' and route.action == 'GATHER_EVIDENCE':
                next_route = await orchestrator.decide(PROJECT, max_repairs=0)
                result['next_route'] = next_route.model_dump(mode='json')
                if next_route.action in ('STOP', 'ACCEPT_HYPOTHESIS', 'REJECT_HYPOTHESIS'):
                    await orchestrator.execute_adaptive(next_route)
        else:
            await orchestrator.execute_adaptive(route)
            selection = await orchestrator.decide(PROJECT, max_repairs=0)
            if selection.action == 'SELECT_EXPERIMENT':
                spec = selected_experiment(load_snapshot(ledger, PROJECT))
                FeasibilityService(ledger).assess(PROJECT, spec.experiment_id)
                ApprovalService(ledger).request_approval(PROJECT, spec.experiment_id)
                result = {'status': 'AWAITING_HUMAN_APPROVAL', 'experiment_id': spec.experiment_id,
                          'executed': False, 'fresh_approval_required': True}
            else:
                result = {'status': 'LEGAL_DIVERGENCE', 'chosen_action': selection.action.value, 'executed': False}
        path = save(label, info, ledger, route=route.model_dump(mode='json'), result=result,
                    planner_calls=planner.calls, phase13_implemented=False)
        print('AUTOLAB_ADAPTIVE_FOLLOWUP_OK' if result['status'] == 'AWAITING_HUMAN_APPROVAL' else 'LEGAL_DIVERGENCE')
        print('Action:', route.action, 'Rationale:', route.reason)
        print('Status:', result['status'], 'Artifact:', path)
    return info, result


if __name__ == '__main__':
    asyncio.run(smoke())
