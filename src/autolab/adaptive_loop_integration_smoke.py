"""Bounded live smoke. Full two-round path is also verified offline.

When live PI diverges, persist the legal choice without forcing an experiment.
When it selects a new spec, stop at the production human boundary. A separately
reviewable test-human continuation uses the existing downstream service contracts.
"""
import asyncio
import os
import subprocess
import sys
from uuid import uuid4
from autolab.config import PROJECT_ROOT
from autolab.adaptive_followup_integration_smoke import smoke


def validate_offline():
    artifact = PROJECT_ROOT / 'results/phase12-deterministic-loop-smoke.json'
    root = PROJECT_ROOT / 'results/phase12-artifacts' / ('offline-' + uuid4().hex)
    subprocess.run([sys.executable, '-m', 'pytest', '-q',
        'tests/test_adaptive.py::test_full_two_round_vertical_slice_reuses_every_downstream_service',
        '--basetemp', str(root)], cwd=PROJECT_ROOT,
        env={**os.environ, 'AUTOLAB_PHASE12_ARTIFACT': str(artifact)}, check=True)
    print('AUTOLAB_ADAPTIVE_LOOP_OK: deterministic two-round slice; paid calls=0')
    print('Artifact:', artifact)


async def resume_after_inspection(database):
    """Explicit recovery after pre-call failure; never repeat finished specialists."""
    from pathlib import Path
    from autolab.config import configure
    from autolab.ledger import ResearchLedger
    from autolab.planner.service import OmnigentPlanner
    from autolab.orchestration.orchestrator import Orchestrator
    from autolab.orchestration.snapshot import load_snapshot
    from autolab.adaptive_smoke_helpers import save, PROJECT
    configure()
    with ResearchLedger(database) as ledger:
        before = load_snapshot(ledger, PROJECT)
        if (not any(e.event_type == 'LOCAL_RESULT_EVIDENCE_INSPECTED' for e in before.events)
            or not any(e.event_type == 'ADAPTIVE_CONTROL_RETURNED' for e in before.events)
            or any(d.action == 'STOP' for d in before.decisions)):
            raise RuntimeError('Resume requires completed local inspection and no terminal decision')
        planner = OmnigentPlanner()
        orchestrator = Orchestrator(ledger, planner)
        route = await orchestrator.decide(PROJECT, max_repairs=0)
        if route.action in ('STOP', 'ACCEPT_HYPOTHESIS', 'REJECT_HYPOTHESIS'):
            await orchestrator.execute_adaptive(route)
        info = {'database_path': str(Path(database).resolve()), 'root': str(Path(database).resolve().parent),
            'project_id': PROJECT, 'explicit_resume': 'After ContextTooLargeError before final model call; no repeated dispatch'}
        path = save('adaptive-loop', info, ledger, result={'status': 'LEGAL_DIVERGENCE',
            'chosen_action': 'GATHER_EVIDENCE', 'next_route': route.model_dump(mode='json')},
            planner_calls=2, recovery_planner_calls=planner.calls, phase13_implemented=False)
        print('LEGAL_DIVERGENCE: GATHER_EVIDENCE →', route.action.value)
        print('Rationale:', route.reason)
        print('Artifact:', path)


if __name__ == '__main__':
    validate_offline()
    if '--resume-after-inspection' in sys.argv:
        asyncio.run(resume_after_inspection(sys.argv[sys.argv.index('--resume-after-inspection')+1]))
    elif '--offline' not in sys.argv:
        asyncio.run(smoke('adaptive-loop'))
