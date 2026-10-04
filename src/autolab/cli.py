"""Thin human interface to the existing scientific services; all scopes are explicit."""
import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError
from autolab import schemas as s
from autolab.config import configure
from autolab.feasibility.approval import ApprovalService, render_packet
from autolab.feasibility.persistence import current_packet
from autolab.interface import ProjectService
from autolab.ledger import ResearchLedger
from autolab.orchestration.orchestrator import Orchestrator, IllegalDecisionError
from autolab.orchestration.snapshot import load_snapshot
from autolab.planner.service import OmnigentPlanner
from autolab.reporting.public import public
from autolab.reporting.service import ReportService
from autolab.reporting.view import build_view, render_status


def parser():
    root = argparse.ArgumentParser(prog='autolab', description='Adaptive research with explicit human gates and a canonical SQLite ledger.')
    commands = root.add_subparsers(dest='command', required=True)
    from autolab.research_intake import add_parser
    add_parser(commands)
    descriptions = {
        'start': 'Persist an explicit canonical ResearchCharter; no model call.',
        'status': 'Show current derived state, science, decisions and gates; no model call.',
        'continue': 'Run the existing bounded adaptive loop. Reasoning may make paid Omnigent calls; human gates halt work.',
        'approve': 'Explicitly approve the exact current ApprovalPacket. Default scope is preparation only; no run approval.',
        'reject': 'Record an exact scoped human rejection and return control to Planner.',
        'modify': 'Record a human modification request; preserve the ExperimentSpec.',
        'pause': 'Persist a pause; prevent further adaptive continuation. Active work requires separate reconciliation.',
        'resume': 'Resume a paused project without resetting budget, rounds or approval.',
        'stop': 'Persist a terminal human STOP; preserve scientific history.',
        'history': 'Show chronological scientific milestones for this project.',
        'report': 'Atomically regenerate a deterministic Markdown report from this ledger/project; no LLM.',
    }
    for name, description in descriptions.items():
        cmd = commands.add_parser(name, help=description, description=description)
        cmd.add_argument('--db', type=Path, required=True, help='Explicit SQLite ledger path; fixture ledgers are never discovered automatically.')
        if name != 'start':
            cmd.add_argument('--project', required=True, help='Exact project ID in the selected ledger.')
        if name == 'start':
            cmd.add_argument('--charter', type=Path, help='Canonical ResearchCharter JSON; mutually exclusive with intake fields.')
            cmd.add_argument('--question', help='Required research question when using explicit intake fields.')
            cmd.add_argument('--objective', help='Required scientific objective.')
            cmd.add_argument('--primary-outcome', help='Required primary outcome; never inferred from the question.')
            cmd.add_argument('--success-criterion', help='Required explicit success criterion.')
            cmd.add_argument('--title', help='Display title; defaults to the supplied question.')
            cmd.add_argument('--budget-usd', type=float, help='Default 0 USD: no consequential spending allocation.')
            cmd.add_argument('--time-minutes', type=float, help='Elapsed charter time limit; default 0 means unconfigured.')
            cmd.add_argument('--max-rounds', type=int, help='Default 1 bounded research round with explicit intake fields.')
        if name in ('status', 'report'):
            cmd.add_argument('--json', action='store_true', help='Emit the same deterministic view/receipt as structured JSON.')
        if name == 'continue':
            cmd.add_argument('--max-steps', type=int, default=4, help='Bounded scientific decisions, 1–20; default 4. Exact adapters remain operator-configured.')
        if name in ('approve', 'reject', 'modify'):
            cmd.add_argument('--packet', required=True, help='Exact current APKT ID; inspect through the existing approval show command.')
            cmd.add_argument('--note', help='Concise public human note, without credentials.')
        if name == 'approve':
            cmd.add_argument('--yes', action='store_true', help='Explicit non-interactive human confirmation of this exact packet.')
            cmd.add_argument('--max-cost-usd', type=float)
            cmd.add_argument('--max-runtime-minutes', type=float)
            cmd.add_argument('--acknowledge-unknowns', action='store_true')
            cmd.add_argument('--include-implementation', action='store_true', help='Explicitly include implementation eligibility; does not grant execution permission.')
        if name in ('pause', 'resume', 'stop'):
            cmd.add_argument('--note', help='Public reason for this human control action.')
        if name == 'report':
            cmd.add_argument('--reports-dir', type=Path, help='Report root; output is scoped by project ID and ledger path digest.')
    return root


def intake(args, ledger):
    fields = ('question', 'objective', 'primary_outcome', 'success_criterion', 'title', 'budget_usd', 'time_minutes', 'max_rounds')
    if args.charter:
        if any(getattr(args, f) is not None for f in fields):
            raise ValueError('--charter cannot be combined with scientific intake fields.')
        return s.ResearchCharter.model_validate_json(args.charter.read_text())
    missing = [f.replace('_', '-') for f in fields[:4] if not getattr(args, f)]
    if missing:
        raise ValueError('Start requires explicit ' + ', '.join('--' + f for f in missing) + '; alternatively use --charter.')
    return s.ResearchCharter(project_id=ledger.next_id('PROJECT'), title=args.title or args.question,
        research_question=args.question, objective=args.objective, primary_outcome=args.primary_outcome,
        success_criteria={'criterion': args.success_criterion}, budget_usd=args.budget_usd if args.budget_usd is not None else 0,
        max_runtime_minutes=args.time_minutes if args.time_minutes is not None else 0,
        constraints={'max_rounds': args.max_rounds if args.max_rounds is not None else 1})


def main(argv=None, *, input_fn=None, orchestrator_factory=None, services=None, actor='human', allow_test_human=False):
    args = parser().parse_args(argv)
    configure()
    def emit(value):
        print(public(str(value)))
    try:
        if args.command == 'research':
            from autolab.research_intake import run_intake
            return run_intake(args, input_fn=input_fn, orchestrator_factory=orchestrator_factory, services=services)
        # A typo in --db must not create an empty ledger for an existing-project command.
        if args.command != 'start' and not args.db.is_file():
            raise ValueError('Ledger does not exist at the explicit --db path; select the correct ledger or start a project.')
        with ResearchLedger(args.db) as ledger:
            if args.command == 'start':
                charter = ProjectService(ledger).start(intake(args, ledger))
                emit(f'Project created: {charter.project_id}\nLedger: {args.db.resolve()}\nSTATE {build_view(ledger, charter.project_id)["state"]}')
            elif args.command == 'status':
                view = build_view(ledger, args.project)
                emit(json.dumps(view, sort_keys=True, indent=2, allow_nan=False) if args.json else render_status(view))
            elif args.command == 'report':
                receipt = ReportService(ledger, root=args.reports_dir).generate(args.project)
                emit(json.dumps(receipt, sort_keys=True, indent=2) if args.json else
                    f"Research report generated: {receipt['path']}\nProject: {receipt['project_id']}\nStatus: {receipt['state']}\nRounds: {receipt['rounds']}\nExperiments: {receipt['experiments']}")
            elif args.command == 'continue':
                before = build_view(ledger, args.project)
                event_ids = {e['event_id'] for e in before['milestones']}
                orchestrator = orchestrator_factory(ledger) if orchestrator_factory else Orchestrator(ledger, OmnigentPlanner())
                result = asyncio.run(orchestrator.continue_research(args.project, max_steps=args.max_steps, services=services))
                after = build_view(ledger, args.project)
                executed = [e for e in after['milestones'] if e['event_id'] not in event_ids and
                    e['event_type'] == 'ADAPTIVE_CONTROL_RETURNED']
                emit(f"Previous state: {before['state']}\nContinuation: {result['status']}\nDecisions: {', '.join(result['decisions']) or 'none'}")
                action_by_id = {d['decision_id']: d['action'] for d in after['decisions']}
                emit('Actions actually executed: ' + ('; '.join(action_by_id.get(e['decision_id'], 'UNKNOWN') +
                    ' / ' + str(e['decision_id']) + ' / ' + e['event_id'] for e in executed) or 'none'))
                emit(render_status(after))
            elif args.command in ('approve', 'reject', 'modify'):
                snapshot = load_snapshot(ledger, args.project)
                packet = current_packet(snapshot)
                if not packet or packet.packet_id != args.packet:
                    previous = next((e.payload.get('packet') for e in reversed(snapshot.events)
                        if e.payload.get('packet', {}).get('packet_id') == args.packet), None)
                    if previous:
                        latest = ledger.get_experiment(previous['experiment_id'])
                        raise ValueError(f"ApprovalPacket {args.packet} targets {previous['experiment_id']} v{previous['experiment_version']}; "
                            f"current spec is v{latest.version if latest else 'UNKNOWN'}. Review a fresh packet for the current selection/assessment.")
                    raise ValueError(f'ApprovalPacket {args.packet} is not current in project {args.project}; inspect the exact selected experiment and request a current packet.')
                emit(render_packet(packet))
                if args.command == 'approve' and not args.yes:
                    if input_fn is None and not sys.stdin.isatty():
                        raise ValueError('Approval requires explicit confirmation; use --yes for a non-interactive human command.')
                    answer = (input_fn or input)(f'Type APPROVE {packet.packet_id} to confirm: ').strip()
                    if answer != f'APPROVE {packet.packet_id}':
                        raise ValueError('Approval not confirmed; no human decision persisted.')
                options = {}
                if args.command == 'approve':
                    options = {'max_cost_usd': args.max_cost_usd, 'max_runtime_minutes': args.max_runtime_minutes,
                        'acknowledge_unknowns': args.acknowledge_unknowns,
                        'approved_actions': ['PREPARE_RESOURCES', 'IMPLEMENT_EXPERIMENT'] if args.include_implementation else None}
                event = ApprovalService(ledger, allow_test_human=allow_test_human).record_human_decision(
                    args.project, packet.experiment_id, packet.experiment_version, args.command.upper(),
                    packet_id=args.packet, actor=actor, note=args.note, **options)
                emit(f'Persisted {event.event_type}: {event.event_id}; {packet.experiment_id} v{packet.experiment_version}. Control returns to Planner.')
            elif args.command in ('pause', 'resume', 'stop'):
                event = ProjectService(ledger, allow_test_human=allow_test_human).control(args.project, args.command, note=args.note, actor=actor)
                emit(f"Persisted {event.event_type}: {event.event_id}\nSTATE {build_view(ledger, args.project)['state']}")
            elif args.command == 'history':
                view = build_view(ledger, args.project)
                emit('\n'.join(f"{e['created_at']} {e['event_id']} {e['event_type']}: {e['summary']}" for e in view['milestones']) or 'No milestones recorded.')
        return 0
    except ValidationError as error:
        emit('Invalid canonical input: ' + '; '.join('.'.join(str(x) for x in e['loc']) + ': ' + e['msg']
            for e in error.errors(include_input=False, include_url=False)))
        return 2
    except (ValueError, KeyError, OSError, sqlite3.IntegrityError, IllegalDecisionError, EOFError) as error:
        print(public('Error: ' + str(error)), file=sys.stderr)
        return 2
    except Exception as error:
        print(f'Operation failed ({type(error).__name__}); inspect status/history. Completed records are preserved; interrupted work requires explicit reconciliation.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
