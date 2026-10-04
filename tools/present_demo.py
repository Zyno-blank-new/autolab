"""Read-only terminal presentation of the actual saved Phase 14 checkpoint."""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from autolab.reporting.public import public

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'results/final-demo/3139fbc73dbf432da21fb22656440f37/demo.db'
PROJECT = 'PROJECT_AUTOLAB_DEMO'
TABLES = ('projects', 'sources', 'evidence', 'hypotheses', 'reviews',
          'experiment_candidates', 'experiments', 'resources', 'readiness_reports',
          'implementations', 'runs', 'metrics', 'analyses', 'decisions', 'events')


def say(value=''):
    value = public(str(value))
    value = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', value)
    for line in value.split('\n'):
        print(textwrap.fill(line, width=100, subsequent_indent='  ') if line else '')


def heading(title):
    print('\n' + '=' * 76)
    say(title)
    print('=' * 76)


def load(connection):
    return {table: [json.loads(row[0]) for row in connection.execute(
        f'SELECT record_json FROM {table} WHERE project_id=? ORDER BY created_at, rowid',
        (PROJECT,))] for table in TABLES}


def overview(data, connection):
    heading('1 / 5   AUTOLAB | An adaptive computational research lab')
    say('RECORDED LIVE-AGENT CHECKPOINT + CURRENT LOCAL VERIFICATION')
    say('This presentation is offline; it makes no new model calls.')
    say()
    say('Research question: ' + data['projects'][0]['research_question'])
    say()
    say('Question -> Evidence -> Hypotheses -> Design -> Human approval -> Readiness')
    say('Then, when admitted: Audited code -> Execution -> Analysis -> Planner')
    say()
    calls = [e for e in data['events'] if e['event_type'] == 'DEMO_MODEL_INVOCATION']
    roles = {e['payload']['role'] for e in calls if e['payload']['status'] == 'COMPLETED'}
    say(f"Recorded work: {len(data['sources'])} sources | {len(data['evidence'])} evidence records | "
        f"{len(data['hypotheses'])} hypotheses | {len(data['decisions'])} Planner decisions")
    say(f'{len(calls)} model-call attempts across {len(roles)} completed agent roles; billing UNKNOWN.')
    say('Current outcome: readiness BLOCK. No experiment result has been measured.')


def science(data, connection):
    heading('2 / 5   EVIDENCE, COMPETING HYPOTHESES AND A FROZEN DESIGN')
    for source in data['sources']:
        say(f"{source['source_id']}: {source['title']} ({source.get('year', 'year unknown')})")
        say('  ' + str(source.get('url') or source.get('doi') or 'Provenance retained in ledger'))
    say('The papers provide methodological background, not measured clipping efficacy.')
    say()
    for hypothesis in data['hypotheses']:
        say(f"{hypothesis['hypothesis_id']}: {hypothesis['statement']}")
    say()
    experiment = data['experiments'][-1]
    candidates = {c['candidate_id'] for c in data['experiment_candidates']}
    say(f"{len(candidates)} candidate designs, with retained revisions; {len(data['reviews'])} scientific reviews.")
    say(f"Selected: {experiment['experiment_id']} v{experiment['version']} / {experiment['hypothesis_id']}")
    say(f"Frozen cohort: {experiment['dataset_requirements']['cohort']}; "
        f"{len(experiment['dataset_requirements']['frozen_rows'])} synthetic rows; metric: {experiment['primary_metric']}.")
    say('Numerical predictions in the scientific records are prospective deductions, not observations.')


def gates(data, connection):
    heading('3 / 5   HUMAN APPROVAL AND INDEPENDENT READINESS')
    approvals = [e for e in data['events'] if e['event_type'] == 'HUMAN_APPROVED']
    for event in approvals:
        say(f"{event['event_id']}: explicit {event['actor']} approval; "
            f"actions: {', '.join(event['payload'].get('approved_actions', []))}")
    say('These are isolated test-human approvals recorded during the integration.')
    for report in data['readiness_reports']:
        origin = report['metadata'].get('verdict_origin', 'real independent agent review')
        say(f"{report['readiness_id']}: {report['verdict']} | {origin}")
    say()
    say('The original audit found incomplete target isolation, artifact and worker evidence.')
    say('A numeric-equality leakage false positive was subsequently corrected in the validator.')
    say('The final successor proposal changed immutable acceptance criteria and was rejected.')
    say('Two repair attempts were consumed. The original plan, spec and resources remain preserved.')
    say()
    say(f"Implementations: {len(data['implementations'])} | Runs: {len(data['runs'])} | "
        f"Metrics: {len(data['metrics'])} | Analyses: {len(data['analyses'])}")
    say('Approval did not override readiness. Further work requires the Planner/human design flow.')


def events(data, connection):
    heading('4 / 5   AUDIT TRAIL | Actual persisted events, not a live-agent replay')
    kinds = {'EXPERIMENT_SELECTED', 'HUMAN_APPROVED', 'RESOURCE_MANIFEST_CREATED',
             'READINESS_REPAIR_REQUESTED', 'PREPARATION_SUCCESSOR_REJECTED',
             'READINESS_BLOCKED', 'LINKED_RESEARCH_SCOPE_AUTHORIZED'}
    selected = [e for e in data['events'] if e['event_type'] in kinds]
    for event in selected[-12:]:
        stamp = datetime.fromisoformat(event['created_at'].replace('Z', '+00:00')).astimezone(
            ZoneInfo('America/New_York')).strftime('%H:%M:%S %Z')
        say(f"{stamp}  {event['event_id']}  [{event['actor']}] "
            f"{event['event_type']} -> {event.get('target_id') or PROJECT}")
    say()
    say(f"{len(data['events'])} total project events retained in the ledger.")
    say('Each decision and review is linked to versioned scientific artifacts.')


def verify(data, connection):
    heading('5 / 5   LIVE LOCAL INTEGRITY CHECK | No scientific execution')
    if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('SQLite integrity check failed')
    if connection.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Ledger foreign-key check failed')
    say('PASS  SQLite integrity and record relationships')
    manifests = [e['payload']['manifest'] for e in data['events']
                 if e['event_type'] == 'RESOURCE_MANIFEST_CREATED']
    manifest = manifests[-1]
    for pin in manifest['resources']:
        path = Path(pin['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != pin['checksum']:
            raise ValueError('Prepared resource hash mismatch: ' + pin['resource_id'])
        say(f"PASS  {pin['resource_id']} v{pin['version']} SHA-256 matches its manifest")
    original = json.loads((DB.parent / 'recovery_inspection.json').read_text())
    plans = [e['payload']['plan'] for e in data['events'] if e['event_type'] == 'PREPARATION_PLAN_CREATED']
    if data['experiments'][-1] != original['spec'] or plans[-1] != original['plan'] or manifest != original['manifest']:
        raise ValueError('Spec, plan or manifest differs from the inspected checkpoint')
    say('PASS  Original experiment spec, preparation plan and manifest preserved')
    validation = json.loads((ROOT / 'results/phase14-recovery-validation.json').read_text())
    tests = validation['tests']
    say(f"SAVED REGRESSION  {tests['passed']} passed / {tests['failed']} failed (not rerun by this command)")
    say()
    say('DEMO CONCLUSION: Recorded research and guarded progression are demonstrated.')
    say('END-TO-END COMPLETION: INCOMPLETE. No measured result or post-result Planner decision.')
    say('Next: reviewed design/approval flow after the exhausted repair limit; no third repair.')


SCENES = {'overview': overview, 'science': science, 'gates': gates, 'events': events, 'verify': verify}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='Print all five screens without pausing.')
    parser.add_argument('--section', choices=SCENES, help='Show one screen directly.')
    args = parser.parse_args()
    if not DB.is_file():
        parser.exit(1, 'Saved demo ledger is missing. Use the preserved docs/DEMO_REPORT.md checkpoint.\n')
    try:
        with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as connection:
            connection.execute('PRAGMA query_only=ON')
            data = load(connection)
            scenes = [SCENES[args.section]] if args.section else list(SCENES.values())
            for index, scene in enumerate(scenes):
                if index and not args.all and sys.stdin.isatty():
                    input('\nPress Enter for the next screen (Ctrl-C to finish)... ')
                scene(data, connection)
        return 0
    except (OSError, ValueError, KeyError, IndexError, sqlite3.Error) as error:
        say(f'DEMO CHECK FAILED: {error}')
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\nPresentation ended; no research records changed.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
