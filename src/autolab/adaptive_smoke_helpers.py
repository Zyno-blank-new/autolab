"""Isolated authorized checkpoint; original terminal ledgers are read only."""
import hashlib
import json
import sqlite3
from uuid import uuid4
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.ledger.repository import TABLES
from autolab.orchestration.models import ProjectSnapshot
from autolab.orchestration.snapshot import COLLECTIONS, load_snapshot
from autolab.preparation.manifest import fingerprint
from autolab.runtime_smoke_helpers import verify_real_run_blocked

PROJECT = 'PROJECT_PHASE10_ISOLATED'


def create_fixture(label):
    source_path = PROJECT_ROOT / 'results/phase11-result-critique-smoke.json'
    source = json.loads(source_path.read_text())
    snapshot = ProjectSnapshot.model_validate(source['snapshot'])
    parent_db = source['fixture']['database_path']
    conn = sqlite3.connect('file:' + parent_db + '?mode=ro', uri=True)
    try:
        row = conn.execute('SELECT record_json FROM projects WHERE project_id=?', (PROJECT,)).fetchone()
        if not row or s.ResearchCharter.model_validate_json(row[0]) != snapshot.charter:
            raise RuntimeError('Parent charter mismatch')
        for name, model in COLLECTIONS.items():
            table = TABLES[model]
            rows = conn.execute(f'SELECT record_json FROM {table.name} WHERE project_id=? ORDER BY created_at,rowid', (PROJECT,)).fetchall()
            if [model.model_validate_json(row[0]) for row in rows] != getattr(snapshot, name):
                raise RuntimeError('Parent scientific checkpoint mismatch: ' + name)
    finally:
        conn.close()
    cutoff = next(d.created_at for d in snapshot.decisions if d.action == 'STOP')
    root = PROJECT_ROOT / 'results/phase12-artifacts' / uuid4().hex
    root.mkdir(parents=True)
    db = root / 'adaptive.db'
    with ResearchLedger(db) as ledger:
        ledger.create_project(snapshot.charter)
        for name in ('sources', 'evidence', 'hypotheses', 'candidates', 'experiments', 'resources',
                     'readiness', 'implementations', 'runs', 'metrics', 'analyses', 'costs', 'reviews', 'decisions', 'events'):
            items = getattr(snapshot, name)
            if name in ('decisions', 'events'):
                items = [x for x in items if x.created_at < cutoff]
            ledger.add_many(items)
        scope = ledger.create_project(s.ResearchCharter(project_id='PROJECT_PHASE12_SCOPE',
            title='Explicit linked adaptive research scope', research_question=snapshot.charter.research_question,
            objective='Assess whether the fixed-input clipping result warrants further computational work: resolve boundary-crossing mechanism versus coverage uncertainty if scientifically valuable, or stop with calibrated scope.',
            primary_outcome='An auditable result-sensitive next decision; any new experiment requires fresh approval',
            budget_usd=100, max_runtime_minutes=240,
            success_criteria={'decision': 'Reviewed results and limitations support a justified next action or stop'},
            constraints={'parent_project': PROJECT, 'max_rounds': 2, 'max_experiments': 2,
                'scope': 'Phase 12 only; at most one new offline follow-up scientific contract. No inference, training, production approval or Phase 13.',
                'authorization': 'Explicit Phase 12 user request; isolated test-human smoke allowed'},
            stop_conditions=['Two research rounds maximum', 'Hard budget/time exhausted', 'No useful affordable uncertainty-reducing action']))
        ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'), project_id=PROJECT,
            event_type='LINKED_RESEARCH_SCOPE_AUTHORIZED', actor='test-human',
            summary='Explicit Phase 12 authorization on separate pre-STOP checkpoint; parent STOP and scientific records preserved',
            payload={'linked_project_id': scope.project_id, 'linked_charter_fingerprint': fingerprint(scope),
                'parent_charter_fingerprint': fingerprint(snapshot.charter), 'parent_database': parent_db,
                'parent_snapshot_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
                'parent_stop': next(d.model_dump(mode='json') for d in snapshot.decisions if d.action == 'STOP'),
                'label': label, 'scientific_records_imported_verbatim': True}))
        from autolab.analysis.persistence import reviewed_analysis
        if not reviewed_analysis(load_snapshot(ledger, PROJECT)):
            raise RuntimeError('Imported actual reviewed analysis is not current')
    return {'database_path': str(db), 'root': str(root), 'project_id': PROJECT,
            'parent_database': parent_db, 'real_blocked': verify_real_run_blocked()}


def save(label, info, ledger, **extra):
    from autolab.orchestration.adaptive import research_history, round_history, telemetry
    snapshot = load_snapshot(ledger, PROJECT)
    path = PROJECT_ROOT / ('results/phase12-' + label + '-smoke.json')
    path.write_text(json.dumps({'fixture': info, 'snapshot': snapshot.model_dump(mode='json'),
        'research_history': research_history(snapshot), 'telemetry': telemetry(snapshot), **extra}, indent=2, allow_nan=False) + '\n')
    return path
