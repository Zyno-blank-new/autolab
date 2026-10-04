"""Deterministic canonical checks and measured demo telemetry; no model calls."""
import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from autolab.config import PROJECT_ROOT
from autolab.final_demo import PROJECT, require_demo
from autolab.ledger import ResearchLedger
from autolab.literature.provenance import validate_evidence
from autolab.orchestration.adaptive import telemetry
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import current_analysis, latest_review, current_run
from autolab.analysis.persistence import reviewed_analysis
from autolab.runtime.persistence import valid_result
from autolab.reporting.service import ReportService
from autolab.reporting.view import build_view


def final_telemetry(snapshot):
    result=telemetry(snapshot)
    events=snapshot.events
    def pair(start,finish):
        if start is None or finish is None or finish<start:
            return None
        return (finish-start).total_seconds()
    requests=[e for e in events if e.event_type=='HUMAN_APPROVAL_REQUESTED']
    specs={e.experiment_id:e for e in snapshot.experiments}
    result['durations_seconds']['spec_to_approval_request']=[pair(specs[e.payload['packet']['experiment_id']].created_at,e.created_at) for e in requests]
    result['durations_seconds']['result_to_analysis']=[pair(a and next((r.completed_at for r in snapshot.runs if r.run_id==a.run_id),None),a.created_at) for a in snapshot.analyses]
    result['durations_seconds']['analysis_to_next_planner']=[pair(a.created_at,next((d.created_at for d in snapshot.decisions if d.created_at>=a.created_at),None)) for a in snapshot.analyses]
    calls=[e for e in events if e.event_type=='DEMO_MODEL_INVOCATION']
    timings=[e for e in events if e.event_type=='DEMO_ACTION_TIMING']
    result['counts'].update(critic_reviews=sum(r.reviewer_role=='critic' for r in snapshot.reviews),
        implementation_revisions=sum(i.metadata.get('revision',0)>0 for i in snapshot.implementations),
        readiness_repairs=max((r.metadata.get('repair_count',0) for r in snapshot.readiness),default=0),
        model_calls_attempted=len(calls),model_calls_completed=sum(e.payload['status']=='COMPLETED' for e in calls),
        model_calls_failed=sum(e.payload['status']=='FAILED' for e in calls))
    result['durations_seconds']['observed_control_and_specialist_active_wall']=math.fsum(e.payload['duration_seconds'] for e in timings) if timings else None
    result['durations_seconds']['observed_model_wait_wall']=math.fsum(e.payload['duration_seconds'] for e in calls) if calls else None
    result['timing_receipts']={
        'control_steps':[{'event_id':e.event_id,**e.payload} for e in timings],
        'model_calls':[{'event_id':e.event_id,**e.payload} for e in calls]}
    result['measurement_limits']=[
        'Stage latencies are wall-clock timestamps and may include operator/development idle time.',
        'Active wall time is the sum of completed bounded control invocations, including model waiting and deterministic specialist work; it excludes setup, feasibility/approval work outside the invocation and failed invocations without a completion receipt.',
        'Model wait time overlaps active control time; these totals must not be added.',
        'Model calls are transport attempts, not provider-token/billing records; actual dollars remain UNKNOWN.',
        'Automated approval events use explicit test-human; they do not measure real human labor.',
        'No human comparison baseline, wet-lab acceleration, or universal multiplier was measured.']
    return result


def audit(ledger, *, require_complete=True):
    snapshot=load_snapshot(ledger,PROJECT)
    for evidence in snapshot.evidence:
        source=next(p for p in snapshot.sources if p.source_id==evidence.source_id)
        validate_evidence(evidence,source)
    recomputations=[]
    for run in snapshot.runs:
        if not valid_result(snapshot,run):
            raise ValueError('Final run integrity or current exact audit is invalid.')
        raw_pin=run.output_manifest['artifacts']['raw_outputs.jsonl']
        raw=[json.loads(line)['observation'] for line in Path(raw_pin['path']).read_text().splitlines()]
        for metric in (m for m in snapshot.metrics if m.run_id==run.run_id):
            group=[o for o in raw if o['condition']==metric.metadata['condition']]
            if len(group)!=metric.metadata['denominator'] or any(o['status']!='success' for o in group):
                raise ValueError('Raw denominator/status does not match canonical metric.')
            measured=math.fsum(abs(o['outputs']['prediction']-o['outputs']['target']) for o in group)/len(group)
            if not math.isclose(measured,metric.metric_value,rel_tol=1e-12,abs_tol=1e-12):
                raise ValueError('Independent raw metric recomputation disagrees.')
            recomputations.append({'metric_id':metric.metric_id,'condition':metric.metadata['condition'],
                'canonical_value':metric.metric_value,'independent_value':measured,'denominator':len(group),
                'raw_sha256':raw_pin['sha256']})
    analysis=current_analysis(snapshot)
    reviewed=reviewed_analysis(snapshot,analysis)
    post=[d for d in snapshot.decisions if analysis and d.created_at>=analysis.created_at]
    roles={e.payload['role'] for e in snapshot.events if e.event_type=='DEMO_MODEL_INVOCATION' and e.payload['status']=='COMPLETED'}
    expected={'planner','evidence','hypothesis','critic','experiment_designer','preparation','readiness','implementer','code_auditor','analyst'}
    complete=bool(snapshot.evidence and snapshot.hypotheses and len({c.candidate_id for c in snapshot.candidates})==2
        and snapshot.readiness and snapshot.implementations and snapshot.runs and recomputations and reviewed and post and expected<=roles)
    if require_complete and not complete:
        raise ValueError('Final real-agent end-to-end success conditions are incomplete; retain checkpoint honestly.')
    view=build_view(ledger,PROJECT)
    return {'status':'PASS' if complete else 'INCOMPLETE','project_id':PROJECT,'state':view['state'],
        'roles_completed':sorted(roles),'missing_roles':sorted(expected-roles),
        'source_provenance_verified':len(snapshot.evidence),'metric_recomputation':recomputations,
        'analysis_reviewed_current':reviewed,'post_result_decisions':[d.model_dump(mode='json') for d in post],
        'human_scopes':[e.model_dump(mode='json') for e in snapshot.events if e.event_type=='HUMAN_APPROVED'],
        'telemetry':final_telemetry(snapshot),'view':view}


def verify_receipt(receipt):
    """Arithmetic of an exported earlier run; never grants ledger eligibility."""
    if receipt.get('schema')!='autolab.final-demo-receipt.v1' or receipt.get('project_id')!=PROJECT:
        raise ValueError('Not a published final-demo receipt.')
    observations=receipt['observations']
    conditions={m['metadata']['condition'] for m in receipt['metrics']}
    if conditions!={'baseline','clipped'} or len(observations)!=8 or len(receipt['metrics'])!=2:
        raise ValueError('Incomplete published matched comparison.')
    groups={condition:[o for o in observations if o['condition']==condition] for condition in conditions}
    if ([o['sample_id'] for o in groups['baseline']]!=[o['sample_id'] for o in groups['clipped']]
        or len({o['sample_id'] for o in groups['baseline']})!=4):
        raise ValueError('Published pairing/identity mismatch.')
    for base,clipped in zip(groups['baseline'],groups['clipped']):
        if (base['outputs']['target']!=clipped['outputs']['target']
            or clipped['outputs']['prediction']!=min(1.,max(0.,base['outputs']['prediction']))):
            raise ValueError('Published observations violate the declared clipping/scoring rule.')
    for metric in receipt['metrics']:
        if metric['metric_name']!='mean_absolute_error':
            raise ValueError('Unsupported published metric.')
        rows=groups[metric['metadata']['condition']]
        if len(rows)!=metric['metadata']['denominator'] or any(o['status']!='success' for o in rows):
            raise ValueError('Published denominator/failure mismatch.')
        value=math.fsum(abs(o['outputs']['prediction']-o['outputs']['target']) for o in rows)/len(rows)
        if not math.isfinite(value) or not math.isfinite(metric['metric_value']) or not math.isclose(value,metric['metric_value'],rel_tol=1e-12,abs_tol=1e-12):
            raise ValueError('Published metric differs from independent arithmetic.')
    return {'status':'PASS','metrics_recomputed':len(receipt['metrics']),
        'scope':'Earlier published observations only; no live call, database import, or current execution authorization.'}


def export_docs(result, snapshot, receipt):
    original=Path(receipt['path']).read_text()
    portable=original.replace(str(PROJECT_ROOT.resolve())+'/', '')
    caption=('> Persisted earlier real-agent integration. Paths below are normalized to repository-relative references; '
        'scientific records and values are unchanged. Original canonical report SHA-256: `'+receipt['generation']['report_sha256']+'`.\n\n')
    (PROJECT_ROOT/'docs/DEMO_REPORT.md').write_text(caption+portable)
    run=current_run(snapshot)
    raw=run.output_manifest['artifacts']['raw_outputs.jsonl']
    published={'schema':'autolab.final-demo-receipt.v1','project_id':PROJECT,
        'origin':'Canonical completed earlier run; public observation export, not a replacement ledger or run envelope',
        'ledger_snapshot_sha256':result['view']['ledger_fingerprint'],
        'raw_original_sha256':raw['sha256'],'run_id':run.run_id,
        'observations':[json.loads(line)['observation'] for line in Path(raw['path']).read_text().splitlines()],
        'metrics':[m.model_dump(mode='json') for m in snapshot.metrics if m.run_id==run.run_id],
        'analysis':result['view']['current']['analysis'],
        'decisions':result['post_result_decisions'],'telemetry':result['telemetry']}
    # Export only public fields; normalize paths without rebinding source pins.
    from autolab.reporting.public import public
    published=json.loads(json.dumps(public(published)).replace(str(PROJECT_ROOT.resolve())+'/', ''))
    verify_receipt(published)
    (PROJECT_ROOT/'docs/DEMO_RECEIPT.json').write_text(json.dumps(published,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--db',type=Path)
    choice.add_argument('--receipt',type=Path,help='Recompute the published earlier-run observation export; no current ledger gate certification.')
    parser.add_argument('--allow-partial',action='store_true')
    parser.add_argument('--export-docs',action='store_true',help='Export verified canonical report and public raw observations to portable judge-facing docs.')
    args=parser.parse_args()
    if args.receipt:
        print(json.dumps(verify_receipt(json.loads(args.receipt.read_text())),indent=2))
        return
    path=require_demo(args.db)
    with ResearchLedger(path) as ledger:
        result=audit(ledger,require_complete=not args.allow_partial)
        receipt=ReportService(ledger).generate(PROJECT)
        result['report']=str(Path(receipt['path']).relative_to(PROJECT_ROOT))
        if args.export_docs:
            if result['status']!='PASS':
                raise ValueError('Only a fully verified final integration may be exported as the completed demo.')
            export_docs(result,load_snapshot(ledger,PROJECT),receipt)
    output=path.parent/'audit.json'
    output.write_text(json.dumps(result,indent=2)+'\n')
    if result['status']=='PASS':
        # Reset changes latest.json only; this identifies the verified fallback.
        (path.parent.parent/'completed.json').write_text(json.dumps({
            'project_id':PROJECT,'db':str(path.relative_to(PROJECT_ROOT)),
            'report':result['report'],'audit':str(output.relative_to(PROJECT_ROOT))},indent=2)+'\n')
    print(f'FINAL_DEMO_AUDIT {result["status"]}')
    print(f'Canonical metrics independently recomputed: {len(result["metric_recomputation"])}')
    print(f'Report: {result["report"]}')
    print(f'Audit: {output.relative_to(PROJECT_ROOT)}')

if __name__=='__main__':
    main()
