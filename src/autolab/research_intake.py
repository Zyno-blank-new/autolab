"""Interactive topic intake; delegates scientific work to the existing services."""
import asyncio
import shlex
import sys
from pathlib import Path
from uuid import uuid4

from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.event_stream import EventStream
from autolab.feasibility.persistence import ensure_public
from autolab.interface import ProjectService
from autolab.ledger import ResearchLedger
from autolab.orchestration.orchestrator import Orchestrator
from autolab.planner.service import OmnigentPlanner
from autolab.reporting.public import public
from autolab.reporting.view import build_view, render_status


def add_parser(commands):
    parser = commands.add_parser('research', help='Type a topic, review an explicit charter, and start bounded live research.')
    parser.add_argument('topic', nargs='?', help='Your research question; prompted when omitted.')
    parser.add_argument('--objective', help='Scientific objective; prompted when omitted.')
    parser.add_argument('--primary-outcome', help='Outcome or metric; prompted when omitted.')
    parser.add_argument('--success-criterion', help='Explicit criterion; prompted when omitted.')
    parser.add_argument('--budget-usd', type=float, default=2, help='Proposed allocation, not a provider billing cap (default: 2).')
    parser.add_argument('--time-minutes', type=float, default=15, help='Proposed charter window (default: 15).')
    parser.add_argument('--max-steps', type=int, default=1, choices=range(1,21), metavar='1-20', help='Bounded Planner steps in this invocation (default: 1).')
    parser.add_argument('--db', type=Path, help='New ledger path only; otherwise a unique results/research directory.')
    parser.add_argument('--create-only', action='store_true', help='Persist the reviewed charter without model calls.')
    parser.add_argument('--yes', action='store_true', help='Explicitly accept the fully supplied charter and stated call scope; does not approve experiments.')


def emit(value):
    print(public(str(value)), flush=True)


async def run_with_events(ledger, project, path, max_steps, orchestrator_factory, services):
    stream = EventStream(project, path.parent/'process.log')
    async def pump():
        while True:
            stream.refresh(ledger)
            await asyncio.sleep(.25)
    task = asyncio.create_task(pump())
    try:
        orchestrator = orchestrator_factory(ledger) if orchestrator_factory else Orchestrator(ledger, OmnigentPlanner())
        return await orchestrator.continue_research(project, max_steps=max_steps, services=services)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        stream.refresh(ledger)


def run_intake(args, *, input_fn=None, orchestrator_factory=None, services=None):
    interactive = input_fn is not None or sys.stdin.isatty()
    ask = input_fn or input
    emit('AutoLab | Start research from your topic')
    def field(value, label):
        if value is None and interactive:
            value = ask(label + ': ')
        if not value or not value.strip():
            raise ValueError(label + ' is required; supply it interactively or through its option.')
        return value.strip()
    topic = field(args.topic, 'Research topic / question')
    objective = field(args.objective, 'What do you want to find out')
    outcome = field(args.primary_outcome, 'Primary outcome or metric')
    criterion = field(args.success_criterion, 'What would count as success')
    charter = s.ResearchCharter(project_id='PROJECT_RESEARCH_'+uuid4().hex[:12].upper(),
        title=topic, research_question=topic, objective=objective, primary_outcome=outcome,
        success_criteria={'criterion': criterion}, budget_usd=args.budget_usd,
        max_runtime_minutes=args.time_minutes, constraints={'max_rounds':6, 'max_experiments':1},
        stop_conditions=['Stop at explicit human approval gates, exhausted limits, or unsupported execution requirements.'])
    ensure_public(charter)
    if not args.create_only and (charter.budget_usd<=0 or charter.max_runtime_minutes<=0):
        raise ValueError('Live research needs positive budget and time allocations; use --create-only for intake without calls.')
    path = (args.db or PROJECT_ROOT/'results/research'/uuid4().hex/'research.db').expanduser().resolve()
    if path.exists():
        raise ValueError('Research intake requires a NEW ledger; use status/continue for an existing project.')
    emit('\nReview your research charter:')
    emit(f'Question: {topic}\nObjective: {objective}\nOutcome: {outcome}\nSuccess: {criterion}')
    emit(f'Allocation: ${charter.budget_usd:g}; window: {charter.max_runtime_minutes:g} minutes; '
         f'{args.max_steps} Planner step(s), up to 6 research rounds and 1 experiment per charter.')
    emit('Provider billing is UNKNOWN; the allocation is not an enforceable dollar cap.')
    emit('Experiment preparation, implementation and execution retain their existing approval gates.')
    emit('Mode: save charter only.' if args.create_only else 'Mode: real Omnigent Planner and its selected legal specialist work; model calls may incur charges.')
    if not args.yes:
        if not interactive:
            raise ValueError('Explicit confirmation required; use --yes with all scientific fields supplied.')
        if ask('\nType START to accept this charter and begin: ').strip() != 'START':
            emit('Cancelled. No project created and no model calls made.')
            return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with ResearchLedger(path) as ledger:
        ProjectService(ledger).start(charter)
        emit(f'\nProject: {charter.project_id}\nLedger: {path}')
        scope = f'--db {shlex.quote(str(path))} --project {charter.project_id}'
        emit(f'Inspect anytime: autolab status {scope}')
        emit(f'Continue later: autolab continue {scope} --max-steps 1')
        emit(f'View history: autolab history {scope}')
        emit(f'Generate report: autolab report {scope}')
        try:
            if not args.create_only:
                emit('\nStarting live research. Model responses can take several minutes. Persisted events appear below.')
                result = asyncio.run(run_with_events(ledger, charter.project_id, path, args.max_steps, orchestrator_factory, services))
                emit(f"\nContinuation: {result['status']}; decisions: {', '.join(result['decisions']) or 'none'}")
        finally:
            emit('\n' + render_status(build_view(ledger, charter.project_id)))
    return 0
