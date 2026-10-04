"""Offline isolated CLI start/status/pause/resume smoke; no paid reasoning."""
import json
from pathlib import Path
from uuid import uuid4

from autolab.cli import main
from autolab.config import PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import derive_control_state


def smoke():
    root = PROJECT_ROOT / 'results' / 'phase13-artifacts' / uuid4().hex
    root.mkdir(parents=True)
    db = root / 'cli.db'
    assert main(['start', '--db', str(db), '--question', 'Which controlled uncertainty needs a test?',
        '--objective', 'Define an auditable computational investigation', '--primary-outcome', 'Preregistered comparison',
        '--success-criterion', 'A reviewed, scoped answer', '--budget-usd', '0', '--max-rounds', '1']) == 0
    with ResearchLedger(db) as ledger:
        project = ledger.get_project('PROJECT_0001')
        before = load_snapshot(ledger, project.project_id)
    scope = ['--db', str(db), '--project', project.project_id]
    assert main(['status', *scope]) == 0
    assert main(['pause', *scope, '--note', 'Explicit isolated test pause']) == 0
    assert main(['status', *scope]) == 0
    with ResearchLedger(db) as ledger:
        assert derive_control_state(load_snapshot(ledger, project.project_id)) == 'PAUSED'
    assert main(['continue', *scope]) == 0  # halts without a model call
    assert main(['resume', *scope]) == 0
    with ResearchLedger(db) as ledger:
        after = load_snapshot(ledger, project.project_id)
        assert after.charter == before.charter and after.decisions == before.decisions
        assert derive_control_state(after) == 'INITIALIZED'
    (root / 'validation.json').write_text(json.dumps({'project_id': project.project_id,
        'database_path': str(db), 'paused_then_resumed': True, 'state_retained': True, 'paid_calls': 0}, indent=2) + '\n')
    print('AUTOLAB_CLI_OK')


if __name__ == '__main__':
    smoke()
