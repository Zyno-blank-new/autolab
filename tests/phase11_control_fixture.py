"""Explicit trusted analysis receipts for control-plane regression tests."""
from autolab import schemas as s
from autolab.preparation.manifest import fingerprint
from autolab.analysis.result_summary import build_result_summary

def pin_analysis_fixture(snapshot,analysis):
    summary=build_result_summary(snapshot)
    analysis=analysis.model_copy(update={'run_id':summary.run_id,'hypothesis_id':summary.hypothesis_id,
        'hypothesis_version':summary.hypothesis_version,'metric_ids':[m['metric_id'] for m in summary.metrics],
        'evidence_pins':summary.pins,'criteria_evaluation':summary.criteria})
    events=[*snapshot.events,s.EventRecord(event_id='EVENT_CONTROL_ANALYSIS',project_id=analysis.project_id,
        event_type='SCIENTIFIC_ANALYSIS_CREATED',actor='analyst',target_type='analyses',target_id=analysis.analysis_id,
        summary='Explicit offline mocked analysis receipt',payload={'version':1,'analysis_fingerprint':fingerprint(analysis),
            'result_summary':summary.model_dump(mode='json')})]
    reviews=[r.model_copy(update={'reviewer_role':'critic','metadata':{'analysis_fingerprint':fingerprint(analysis),'evidence_pins':summary.pins}})
        if r.review_type=='analysis' else r for r in snapshot.reviews]
    return snapshot.model_copy(update={'analyses':[analysis],'events':events,'reviews':reviews})
