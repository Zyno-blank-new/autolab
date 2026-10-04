"""Analysis-only checkpoint branch: exact real Phase 10 evidence, no new execution."""
import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.orchestration.models import ProjectSnapshot
from autolab.orchestration.snapshot import load_snapshot, COLLECTIONS
from autolab.runtime.persistence import valid_result
from autolab.runtime_smoke_helpers import verify_real_run_blocked
from autolab.preparation.manifest import fingerprint

PROJECT='PROJECT_PHASE10_ISOLATED'
SCOPE='PROJECT_PHASE11_ANALYSIS_SCOPE'
POINTER=PROJECT_ROOT/'results/phase11-analysis-fixture.json'


def create_fixture():
    source=json.loads((PROJECT_ROOT/'results/phase10-runtime-smoke.json').read_text())
    snap=ProjectSnapshot.model_validate(source['snapshot'])
    # Preserve provenance of the terminal parent. The branch is a checkpoint
    # immediately before STOP, with an explicitly linked new analysis charter.
    # No original DB is opened writable and no scientific record is rebound.
    conn=sqlite3.connect('file:'+source['database_path']+'?mode=ro',uri=True)
    try:
        charter_row=conn.execute('SELECT record_json FROM projects WHERE project_id=?',(PROJECT,)).fetchone()
        if not charter_row or s.ResearchCharter.model_validate_json(charter_row[0])!=snap.charter:
            raise RuntimeError('Saved charter differs from read-only parent ledger')
        for name,model in COLLECTIONS.items():
            from autolab.ledger.repository import TABLES
            table=TABLES[model]
            rows=conn.execute(f'SELECT record_json FROM {table.name} WHERE project_id=? ORDER BY created_at,rowid',(PROJECT,)).fetchall()
            if [model.model_validate_json(r[0]) for r in rows]!=getattr(snap,name):
                raise RuntimeError('Saved Phase 10 snapshot differs from read-only ledger')
    finally: conn.close()
    if not all(valid_result(snap,r) for r in snap.runs): raise RuntimeError('Parent execution is not valid')
    root=PROJECT_ROOT/'results/phase11-artifacts'/uuid4().hex;root.mkdir(parents=True)
    db=root/'analysis.db'
    with ResearchLedger(db) as ledger:
        ledger.create_project(snap.charter)
        charter=s.ResearchCharter(project_id=SCOPE,title='Linked Phase 11 analysis-only charter',
            research_question=snap.charter.research_question,
            objective='Interpret and independently critique the existing completed fixed-input Phase 10 evidence; preserve uncertainty and return Planner routing control',
            primary_outcome='Reviewed experiment-scoped ScientificAnalysis',budget_usd=100,max_runtime_minutes=0,
            constraints={'parent_project':PROJECT,'parent_charter_fingerprint':fingerprint(snap.charter),
                'parent_snapshot_sha256':hashlib.sha256((PROJECT_ROOT/'results/phase10-runtime-smoke.json').read_bytes()).hexdigest(),
                'scope':'Analysis and critique of existing runs only; no execution, changed hypotheses, new metrics or Phase 12 dispatch',
                'authorization':'Explicit Phase 11 user request'})
        ledger.create_project(charter)
        cutoff=next(d.created_at for d in snap.decisions if d.action==s.PlannerAction.STOP)
        records=[]
        for name in ('sources','evidence','hypotheses','candidates','experiments','resources','readiness','implementations','runs','metrics','analyses','costs','reviews','decisions','events'):
            items=getattr(snap,name)
            if name=='decisions':items=[d for d in items if d.created_at<cutoff]
            if name=='events':items=[e for e in items if e.created_at<cutoff]
            records.extend(items)
        # Reviews require their canonical targets, now all inserted earlier.
        ledger.add_many(records)
        ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'),project_id=PROJECT,
            event_type='RESULT_INTERPRETATION_AUTHORIZED',actor='test_human',
            summary='Explicit Phase 11 analysis scope on a separate pre-STOP checkpoint branch; original terminal project unchanged',
            payload={'analysis_charter':charter.model_dump(mode='json'),'parent_database':source['database_path'],
                'parent_stop_decision':next(d.model_dump(mode='json') for d in snap.decisions if d.action==s.PlannerAction.STOP),
                'source_run_ids':[r.run_id for r in snap.runs],'scientific_records_imported_verbatim':True}))
        assert all(valid_result(load_snapshot(ledger,PROJECT),r) for r in snap.runs)
    info={'database_path':str(db),'root':str(root),'project_id':PROJECT,'analysis_charter_id':SCOPE,
        'parent_database_path':source['database_path'],'real_blocked':verify_real_run_blocked()}
    POINTER.write_text(json.dumps(info,indent=2)+'\n')
    return info


def fixture():
    if not POINTER.exists(): raise RuntimeError('Run analysis_integration_smoke first')
    return json.loads(POINTER.read_text())


def save(name,ledger,extra):
    snap=load_snapshot(ledger,PROJECT)
    artifact=PROJECT_ROOT/'results'/name
    artifact.write_text(json.dumps({'fixture':fixture(),'snapshot':snap.model_dump(mode='json'),**extra},indent=2,allow_nan=False)+'\n')
    return artifact
