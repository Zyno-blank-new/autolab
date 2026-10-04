"""Explicit test-human CLI approval in a fresh, isolated canonical ledger."""
import asyncio
import json
from uuid import uuid4

from autolab import schemas as s
from autolab.cli import main
from autolab.config import PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.experiment_selection_smoke_helpers import seed_selection_ready
from autolab.feasibility.approval import ApprovalService
from autolab.feasibility.service import FeasibilityService
from autolab.feasibility_smoke_helpers import explicit_test_planning
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_experiment, approval_for


def seed_packet(ledger):
    project, _ = seed_selection_ready(ledger)  # exact committed scientific fixture, never auto-detected smoke state
    class Selection:
        async def propose(self, context, decision_id, feedback=None):
            return s.NextDecision(decision_id=decision_id, project_id=project.project_id,
                action='SELECT_EXPERIMENT', target_agent='planner', reason='Explicit offline approval-interface fixture selection',
                required_context_ids=[context.summaries['candidates'][0]['id']],
                remaining_budget_usd=project.budget_usd).model_dump_json()
    asyncio.run(Orchestrator(ledger, Selection()).decide(project.project_id, max_repairs=0))
    spec = selected_experiment(load_snapshot(ledger, project.project_id))
    registry, inputs = explicit_test_planning(spec)
    FeasibilityService(ledger, registry).assess(project.project_id, spec.experiment_id, inputs)
    packet = ApprovalService(ledger).request_approval(project.project_id, spec.experiment_id)
    return project, spec, packet


def smoke():
    root = PROJECT_ROOT / 'results' / 'phase13-artifacts' / uuid4().hex
    root.mkdir(parents=True)
    db = root / 'approval.db'
    with ResearchLedger(db) as ledger:
        project, spec, packet = seed_packet(ledger)
    assert main(['approve', '--db', str(db), '--project', project.project_id,
        '--packet', packet.packet_id, '--yes', '--note', 'Explicit isolated CLI test approval only'],
        actor='test-human', allow_test_human=True) == 0
    with ResearchLedger(db) as ledger:
        snapshot = load_snapshot(ledger, project.project_id)
        scope = approval_for(snapshot, s.PlannerAction.PREPARE_RESOURCES)
        assert scope and scope.packet_id == packet.packet_id and scope.experiment_version == spec.version
        assert not approval_for(snapshot, s.PlannerAction.RUN_EXPERIMENT)
        assert not snapshot.runs and not snapshot.implementations and not snapshot.resources
        event = next(e for e in snapshot.events if e.event_type == 'HUMAN_APPROVED')
        assert event.actor == 'test-human'
    (root / 'validation.json').write_text(json.dumps({'project_id': project.project_id, 'database_path': str(db),
        'event': event.model_dump(mode='json'), 'run_approval': False, 'paid_calls': 0}, indent=2) + '\n')
    print('AUTOLAB_CLI_APPROVAL_OK')


if __name__ == '__main__':
    smoke()
