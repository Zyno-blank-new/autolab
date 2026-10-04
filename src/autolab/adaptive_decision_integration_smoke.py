"""One actual Omnigent PI call; persist decision/lineage without dispatch."""
import asyncio
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.planner.service import OmnigentPlanner
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.context_builder import ContextBuilder
from autolab.adaptive_smoke_helpers import create_fixture, save, PROJECT


async def smoke():
    configure()
    info = create_fixture('adaptive-decision')
    with ResearchLedger(info['database_path']) as ledger:
        planner = OmnigentPlanner()
        context = ContextBuilder().build(load_snapshot(ledger, PROJECT))
        route = await Orchestrator(ledger, planner).decide(PROJECT, max_repairs=0)
        path = save('adaptive-decision', info, ledger, route=route.model_dump(mode='json'),
                    context=context.model_dump(mode='json'), planner_calls=planner.calls, executed=False)
        print('AUTOLAB_ADAPTIVE_DECISION_OK')
        print('Action:', route.action, 'Target:', route.target_role, 'Legal: yes', 'Executed: no')
        print('Rationale:', route.reason)
        print('Artifact:', path)
    return info, route


if __name__ == '__main__':
    asyncio.run(smoke())
