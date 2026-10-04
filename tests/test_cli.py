"""Thin CLI integration tests. No paid model/network calls."""
import json
import subprocess
import sys
from pathlib import Path
import pytest

from autolab import schemas as s
from autolab.cli import main
from autolab.cli_approval_integration_smoke import seed_packet
from autolab.interface import ProjectService
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import approval_for
from autolab.orchestration.orchestrator import Orchestrator
from autolab.reporting.view import build_view
from phase13_helpers import charter


@pytest.fixture
def project(ledger):
    return charter(ledger)


@pytest.fixture
def approval(ledger):
    return seed_packet(ledger)


def scope(ledger, project):
    return ['--db', ledger.database.path, '--project', project.project_id]


@pytest.mark.parametrize('module', ['autolab', 'autolab.cli'])
def test_module_entrypoint(module):
    result = subprocess.run([sys.executable, '-m', module, '--help'], capture_output=True, text=True)
    assert result.returncode == 0 and 'Adaptive research' in result.stdout


@pytest.mark.parametrize('command', [None, 'start', 'status', 'continue', 'approve', 'report', 'reject', 'modify', 'pause', 'resume', 'stop', 'history'])
def test_help(command, capsys):
    with pytest.raises(SystemExit) as error:
        main(([command] if command else []) + ['--help'])
    assert error.value.code == 0 and 'usage:' in capsys.readouterr().out


def test_installed_console_entrypoint():
    script = Path(sys.executable).parent / 'autolab'
    result = subprocess.run([str(script), '--help'], capture_output=True, text=True)
    assert result.returncode == 0 and 'status' in result.stdout


def test_start_explicit_safe_defaults(tmp_path, capsys):
    db = tmp_path / 'new.db'
    assert main(['start', '--db', str(db), '--question', 'Question?', '--objective', 'Objective',
        '--primary-outcome', 'Paired error', '--success-criterion', 'Lower error']) == 0
    from autolab.ledger import ResearchLedger
    with ResearchLedger(db) as ledger:
        p = ledger.get_project('PROJECT_0001')
        assert p and p.budget_usd == 0 and p.max_runtime_minutes == 0 and p.constraints['max_rounds'] == 1
    assert 'PROJECT_0001' in capsys.readouterr().out


def test_start_structured_charter(tmp_path):
    file = tmp_path / 'charter.json'
    file.write_text(s.ResearchCharter(project_id='PROJECT_FILE', title='Explicit', research_question='Question?',
        objective='Objective', primary_outcome='Error').model_dump_json())
    assert main(['start', '--db', str(tmp_path/'a.db'), '--charter', str(file)]) == 0


@pytest.mark.parametrize('extra', [[], ['--budget-usd', '-1'], ['--max-rounds', '0'], ['--max-rounds', '-1']])
def test_invalid_intake_rejected(ledger, extra):
    base = ['start', '--db', ledger.database.path]
    if extra:
        base += ['--question', 'Q', '--objective', 'O', '--primary-outcome', 'P', '--success-criterion', 'S']
    assert main(base+extra) == 2
    assert ledger.get_project('PROJECT_0001') is None


def test_invalid_charter_rejected(tmp_path):
    file = tmp_path/'bad.json'
    file.write_text('{"project_id":"BAD","unknown":true}')
    assert main(['start', '--db', str(tmp_path/'db'), '--charter', str(file)]) == 2


def test_status_valid_and_json_same_model(ledger, project, capsys):
    assert main(['status', *scope(ledger, project)]) == 0
    assert 'STATE INITIALIZED' in capsys.readouterr().out
    assert main(['status', *scope(ledger, project), '--json']) == 0
    output = json.loads(capsys.readouterr().out)
    expected = build_view(ledger, project.project_id)
    for key in ('project_id', 'state', 'ledger_fingerprint', 'current', 'budget', 'rounds', 'latest_decision'):
        assert output[key] == expected[key]


def test_status_unknown_project(ledger, project, capsys):
    assert main(['status', '--db', ledger.database.path, '--project', 'UNKNOWN']) == 2
    assert 'Unknown project' in capsys.readouterr().err


def test_missing_ledger_not_created(tmp_path):
    path = tmp_path/'absent.db'
    assert main(['status', '--db', str(path), '--project', 'PROJECT_A']) == 2
    assert not path.exists()


def test_scope_required():
    with pytest.raises(SystemExit) as error:
        main(['status'])
    assert error.value.code == 2


class StopPlanner:
    def __init__(self):
        self.calls = 0
    async def propose(self, context, decision_id, feedback=None):
        self.calls += 1
        return s.NextDecision(decision_id=decision_id, project_id=context.charter.project_id,
            action='STOP', reason='No approved further test is justified within the explicit scope').model_dump_json()


def test_continue_uses_existing_orchestrator(ledger, project, capsys):
    planner = StopPlanner()
    assert main(['continue', *scope(ledger, project), '--max-steps', '1'],
        orchestrator_factory=lambda ledger: Orchestrator(ledger, planner)) == 0
    assert planner.calls == 1
    output = capsys.readouterr().out
    assert 'Previous state: INITIALIZED' in output and 'stopped=True' in output
    assert ledger.list_decisions(project.project_id)[-1].action == 'STOP'


@pytest.mark.parametrize('state', ['pause', 'stop', 'approval'])
def test_continue_halts_without_planner(ledger, state):
    if state == 'approval':
        project, _, _ = seed_packet(ledger)
    else:
        project = charter(ledger)
        ProjectService(ledger).control(project.project_id, state)
    planner = StopPlanner()
    assert main(['continue', *scope(ledger, project)], orchestrator_factory=lambda l: Orchestrator(l, planner)) == 0
    assert planner.calls == 0


@pytest.mark.parametrize('decision', ['approve', 'reject', 'modify'])
def test_human_decisions_exact_packet(ledger, approval, decision):
    project, spec, packet = approval
    before = ledger.get_experiment(spec.experiment_id)
    extra = ['--yes'] if decision == 'approve' else []
    assert main([decision, *scope(ledger, project), '--packet', packet.packet_id, '--note', 'Explicit public request', *extra]) == 0
    after = load_snapshot(ledger, project.project_id)
    event = next(e for e in reversed(after.events) if e.actor == 'human')
    assert event.payload['experiment_id'] == spec.experiment_id and event.payload['experiment_version'] == spec.version
    assert event.payload['packet_id'] == packet.packet_id and event.payload['note'] == 'Explicit public request'
    assert ledger.get_experiment(spec.experiment_id) == before
    if decision == 'approve':
        assert approval_for(after, s.PlannerAction.PREPARE_RESOURCES)
        assert not approval_for(after, s.PlannerAction.RUN_EXPERIMENT)


def test_interactive_explicit_confirmation(ledger, approval):
    project, spec, packet = approval
    assert main(['approve', *scope(ledger, project), '--packet', packet.packet_id],
        input_fn=lambda _: 'APPROVE '+packet.packet_id) == 0


def test_refused_confirmation_no_approval(ledger, approval):
    project, _, packet = approval
    assert main(['approve', *scope(ledger, project), '--packet', packet.packet_id], input_fn=lambda _: 'yes') == 2
    assert not any(e.event_type == 'HUMAN_APPROVED' for e in ledger.list_events(project.project_id))


def test_noninteractive_without_yes_rejected(ledger, approval, monkeypatch):
    project, _, packet = approval
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    assert main(['approve', *scope(ledger, project), '--packet', packet.packet_id]) == 2


def test_stale_packet_and_previous_approval_rejected(ledger, approval, capsys):
    project, spec, packet = approval
    assert main(['approve', *scope(ledger, project), '--packet', packet.packet_id, '--yes']) == 0
    ledger.add_experiment_spec(spec.model_copy(update={'version': 2, 'primary_metric': 'changed_metric'}))
    assert not approval_for(load_snapshot(ledger, project.project_id), s.PlannerAction.PREPARE_RESOURCES)
    assert main(['approve', *scope(ledger, project), '--packet', packet.packet_id, '--yes']) == 2
    message = capsys.readouterr().err
    assert 'current' in message and 'v1' in message and 'v2' in message


def test_stale_assessment_packet_rejected(ledger, approval):
    from autolab.feasibility.service import FeasibilityService
    from autolab.feasibility_smoke_helpers import explicit_test_planning
    project, spec, packet = approval
    registry, inputs = explicit_test_planning(spec)
    FeasibilityService(ledger, registry).assess(project.project_id, spec.experiment_id, inputs)
    assert main(['approve', *scope(ledger, project), '--packet', packet.packet_id, '--yes']) == 2
    assert not any(e.event_type == 'HUMAN_APPROVED' for e in ledger.list_events(project.project_id))


@pytest.mark.parametrize('value', ['0', '21', '-1'])
def test_cli_continue_step_limit_validation(ledger, project, value):
    planner = StopPlanner()
    assert main(['continue', *scope(ledger, project), '--max-steps', value], orchestrator_factory=lambda l: Orchestrator(l, planner)) == 2
    assert planner.calls == 0


def test_wrong_project_packet_rejected(ledger, approval):
    _, _, packet = approval
    other = charter(ledger, 'PROJECT_OTHER')
    assert main(['approve', *scope(ledger, other), '--packet', packet.packet_id, '--yes']) == 2
    assert not ledger.list_events(other.project_id)


@pytest.mark.parametrize('control', ['pause', 'stop'])
def test_incompatible_control_prevents_approval(ledger, approval, control):
    project, _, packet = approval
    assert main([control, *scope(ledger, project)]) == 0
    assert main(['approve', *scope(ledger, project), '--packet', packet.packet_id, '--yes']) == 2
    assert not any(e.event_type == 'HUMAN_APPROVED' for e in ledger.list_events(project.project_id))


def test_pause_resume_preserves_entire_science(ledger, approval):
    project, _, _ = approval
    before = load_snapshot(ledger, project.project_id)
    assert main(['pause', *scope(ledger, project)]) == 0
    assert main(['resume', *scope(ledger, project)]) == 0
    after = load_snapshot(ledger, project.project_id)
    assert before.model_dump(exclude={'events'}) == after.model_dump(exclude={'events'})
    assert build_view(ledger, project.project_id)['state'] == 'AWAITING_HUMAN_APPROVAL'


def test_human_stop_terminal_and_actor_preserved(ledger, project):
    assert main(['stop', *scope(ledger, project), '--note', 'No further approved work']) == 0
    view = build_view(ledger, project.project_id)
    assert view['terminal'] and view['stopped']
    assert view['human_decisions'][-1]['event_type'] == 'HUMAN_STOPPED'
    assert view['human_decisions'][-1]['actor'] == 'human'
    assert main(['resume', *scope(ledger, project)]) == 2
    assert main(['continue', *scope(ledger, project)], orchestrator_factory=lambda l: Orchestrator(l, StopPlanner())) == 0
    assert not ledger.list_decisions(project.project_id)


def test_llm_actor_cannot_human_control(ledger, project):
    assert main(['stop', *scope(ledger, project)], actor='planner') == 2
    assert not ledger.list_events(project.project_id)


def test_production_cli_disallows_test_human(ledger, approval):
    project, _, packet = approval
    assert main(['approve', *scope(ledger, project), '--packet', packet.packet_id, '--yes'], actor='test-human') == 2


def test_internal_error_exit_without_trace(ledger, project, capsys):
    def fail(_):
        raise RuntimeError('hidden detail must not appear')
    assert main(['continue', *scope(ledger, project)], orchestrator_factory=fail) == 1
    output = capsys.readouterr().err
    assert 'Traceback' not in output and 'hidden detail' not in output


def test_history_project_isolation(ledger, project, capsys):
    other = charter(ledger, 'PROJECT_OTHER')
    ProjectService(ledger).control(other.project_id, 'pause', note='Other private note')
    assert main(['history', *scope(ledger, project)]) == 0
    assert 'Other private note' not in capsys.readouterr().out


def test_cli_report_json_receipt(ledger, project, tmp_path, capsys):
    assert main(['report', *scope(ledger, project), '--reports-dir', str(tmp_path/'reports'), '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['project_id'] == project.project_id and Path(result['path']).is_file()
