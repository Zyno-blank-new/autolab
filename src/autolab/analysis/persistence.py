"""Reviewed interpretation is usable only while exact scientific evidence is current."""
from autolab import schemas as s
from autolab.preparation.manifest import fingerprint
from autolab.orchestration.state_machine import current_run, current_analysis, latest_review
from .result_summary import evidence_pins


def analysis_current(snapshot, analysis):
    try:
        run=current_run(snapshot)
        if not analysis or not run or analysis.run_id!=run.run_id: return False
        if (analysis.project_id,analysis.experiment_id,analysis.experiment_version)!=(run.project_id,run.experiment_id,run.experiment_version): return False
        pins=evidence_pins(snapshot,run)
        if analysis.evidence_pins!=pins or analysis.metric_ids!=list(pins['metric_fingerprints']): return False
        spec=next(e for e in snapshot.experiments if e.experiment_id==run.experiment_id and e.version==run.experiment_version)
        if (analysis.hypothesis_id,analysis.hypothesis_version)!=(spec.hypothesis_id,spec.hypothesis_version): return False
        # A trusted analysis commit receipt prevents canonical schema labels alone from authorizing decisions.
        event=next((e for e in reversed(snapshot.events) if e.actor=='analyst' and e.event_type in ('SCIENTIFIC_ANALYSIS_CREATED','SCIENTIFIC_ANALYSIS_REVISED')
            and e.target_id==analysis.analysis_id and e.payload.get('version')==analysis.version),None)
        return bool(event and event.payload.get('analysis_fingerprint')==fingerprint(analysis)
            and event.payload.get('result_summary',{}).get('pins')==pins)
    except (ValueError,RuntimeError,StopIteration,KeyError,AttributeError): return False


def reviewed_analysis(snapshot, analysis=None):
    analysis=analysis or current_analysis(snapshot)
    if not analysis_current(snapshot,analysis): return False
    review=latest_review(snapshot,s.ScientificAnalysis,analysis.analysis_id,analysis.version,'analysis')
    return bool(review and review.reviewer_role=='critic' and review.verdict==s.ReviewVerdict.PASS
        and review.metadata.get('analysis_fingerprint')==fingerprint(analysis)
        and review.metadata.get('evidence_pins')==analysis.evidence_pins
        and not review.metadata.get('deterministic_guard_findings'))
