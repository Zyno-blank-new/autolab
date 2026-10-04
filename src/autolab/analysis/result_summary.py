"""Deterministic descriptive evidence. No model arithmetic or invented statistics."""
import json
import math
from collections import defaultdict
from pathlib import Path
from autolab.orchestration.state_machine import selected_experiment, current_run, latest_versions
from autolab.preparation.manifest import fingerprint
from autolab.runtime.persistence import valid_result, digest
from .models import ResultSummary, AnalysisError


def comparison_contract(spec):
    # Structured preregistration is preferred; never infer a direction from a metric name.
    structured = spec.success_criteria.get('comparison')
    if structured:
        required={'control','intervention','direction','minimum_improvement'}
        if not required <= set(structured) or set(structured)-required-{'threshold_operator'}:
            raise AnalysisError('Invalid preregistered comparison contract')
        if structured['direction'] not in ('lower','higher') or not isinstance(structured['minimum_improvement'],(int,float)) or not math.isfinite(structured['minimum_improvement']) or structured['minimum_improvement'] < 0:
            raise AnalysisError('Invalid metric direction/threshold')
        expected_operator='>' if structured['minimum_improvement']==0 else '>='
        if structured.get('threshold_operator',expected_operator)!=expected_operator:
            raise AnalysisError('Unsupported preregistered threshold operator')
        return {k:structured[k] for k in required}
    # Exact small protocol's preregistered textual criteria, not generic MAE policy.
    if (spec.success_criteria == {'definition':'Future clipped MAE below baseline; fixture has no inferential claim'}
        and spec.falsification_criteria == {'definition':'Future clipped MAE at or above baseline'}
        and spec.dependent_variables == {'absolute_error':'abs(prediction - target)'}
        and spec.independent_variables.get('condition') == ['baseline','clipped']):
        return {'control':'baseline','intervention':'clipped','direction':'lower','minimum_improvement':0.0}
    return None


def evidence_pins(snapshot, run):
    spec = selected_experiment(snapshot)
    hypothesis = next((h for h in snapshot.hypotheses if h.hypothesis_id==spec.hypothesis_id and h.version==spec.hypothesis_version),None) if spec else None
    if not valid_result(snapshot,run) or not hypothesis or current_run(snapshot) != run:
        raise AnalysisError('Analysis requires current integrity-verified completed run and exact hypothesis')
    # A later scientific version invalidates old interpretation even if selection still pins the old version.
    if any(e.experiment_id==spec.experiment_id and e.version>spec.version for e in snapshot.experiments) or any(h.hypothesis_id==hypothesis.hypothesis_id and h.version>hypothesis.version for h in snapshot.hypotheses):
        raise AnalysisError('Scientific contract/hypothesis superseded')
    metrics=[m for m in snapshot.metrics if m.run_id==run.run_id]
    return {'hypothesis_fingerprint':fingerprint(hypothesis),'spec_fingerprint':fingerprint(spec),
        'run_fingerprint':fingerprint(run),'metric_fingerprints':{m.metric_id:fingerprint(m) for m in metrics},
        'raw_sha256':run.output_manifest['artifacts']['raw_outputs.jsonl']['sha256']}


def build_result_summary(snapshot, run=None):
    run = run or current_run(snapshot)
    pins=evidence_pins(snapshot,run)
    spec=selected_experiment(snapshot)
    artifact=run.output_manifest['artifacts']['raw_outputs.jsonl']
    if artifact['size']>1048576: raise AnalysisError('Raw evidence exceeds Phase 11 bounded profile')
    data=Path(artifact['path']).read_bytes()
    if digest(data)!=artifact['sha256']: raise AnalysisError('Raw changed during summary construction')
    raw=[json.loads(line)['observation'] for line in data.splitlines()]
    if len(raw)>4096: raise AnalysisError('Observation bound exceeded')
    groups=defaultdict(list)
    for item in raw: groups[item['condition']].append(item)
    frozen_count=spec.dataset_requirements.get('min_samples')
    conditions=[]
    for name,items in sorted(groups.items()):
        ids={i['sample_id'] for i in items}
        conditions.append({'condition':name,'observations':len(items),'unique_samples':len(ids),
            'success_count':sum(i['status']=='success' for i in items),
            'failure_count':sum(i['status']!='success' for i in items),
            'missing_sample_count':max(0,frozen_count-len(ids)) if isinstance(frozen_count,int) else None,
            'coverage_basis':'preregistered min_samples lower bound' if isinstance(frozen_count,int) else 'expected sample count unknown'})
    metrics=[{'metric_id':m.metric_id,'name':m.metric_name,'value':m.metric_value,'unit':m.unit,
        'condition':m.metadata.get('condition'),'role':m.metadata.get('role'),
        'denominator':m.metadata.get('denominator'),'direction':m.metadata.get('direction',m.metadata.get('support',{}).get('metric_direction')),
        'raw_sha256':m.metadata['raw_sha256']} for m in snapshot.metrics if m.run_id==run.run_id]
    contract=comparison_contract(spec)
    differences=[]
    if contract:
        for name in [spec.primary_metric,*spec.secondary_metrics]:
            pair={m['condition']:m for m in metrics if m['name']==name}
            if contract['control'] not in pair or contract['intervention'] not in pair: continue
            control,intervention=pair[contract['control']],pair[contract['intervention']]
            direction=contract['direction'] if name==spec.primary_metric else intervention['direction']
            delta=intervention['value']-control['value']
            differences.append({'name':name,'control':control['condition'],'intervention':intervention['condition'],
                'control_value':control['value'],'intervention_value':intervention['value'],
                'intervention_minus_control':delta,'absolute_difference':abs(delta),
                'relative_difference':delta/control['value'] if control['value']!=0 else None,
                'relative_difference_percent':100*delta/control['value'] if control['value']!=0 else None,
                'direction':direction,'improvement':-delta if direction=='lower' else delta if direction=='higher' else None,
                'metric_direction':intervention['direction'],
                'metric_ids':[control['metric_id'],intervention['metric_id']]})
    primary=next((d for d in differences if d['name']==spec.primary_metric),None)
    # Unknown textual rules remain unresolved. Never let an invented threshold determine support.
    criteria={'success_preregistered':spec.success_criteria,'falsification_preregistered':spec.falsification_criteria,
        'comparison':contract,'success_met':None,'falsification_met':None}
    if primary:
        criteria['success_met']=(primary['improvement']>0 if contract['minimum_improvement']==0 else primary['improvement']>=contract['minimum_improvement'])
        if spec.falsification_criteria=={'definition':'Future clipped MAE at or above baseline'}:
            criteria['falsification_met']=primary['improvement']<=0
        else:
            falsification=spec.falsification_criteria.get('comparison',{})
            allowed={'maximum_improvement','control','intervention','direction','threshold_operator'}
            if (falsification.get('maximum_improvement')==0 and not set(falsification)-allowed
                and falsification.get('threshold_operator','<=')=='<='
                and all(falsification.get(k,contract[k])==contract[k] for k in ('control','intervention','direction'))):
                criteria['falsification_met']=primary['improvement']<=0
    warnings=[]
    if any(c['failure_count'] for c in conditions): warnings.append('Failures are present; preserve metric failure policy and denominator')
    if any(c['missing_sample_count'] for c in conditions): warnings.append('Condition coverage is incomplete')
    if not contract: warnings.append('Metric direction/criterion computation unresolved; no guessed threshold')
    if len(conditions)<2: warnings.append('Condition comparison unavailable')
    readiness=next((r for r in reversed(snapshot.readiness) if r.experiment_id==spec.experiment_id and r.experiment_version==spec.version),None)
    if readiness: warnings.extend(readiness.warnings)
    impl=next(i for i in snapshot.implementations if i.implementation_id==run.implementation_id)
    # Planning-stage notes are not current runtime warnings. Preserve them in
    # labeled context alongside the actual pinned validation receipt instead.
    limitations=list(spec.potential_confounders)
    from autolab.implementation.persistence import current_checks
    checks=current_checks(snapshot,impl)
    audit=next(r for r in reversed(snapshot.reviews) if r.review_type=='code' and r.target_id==impl.implementation_id)
    validation={'implementation_id':impl.implementation_id,'code_hash':impl.code_version,
        'audit_id':audit.review_id,'audit_verdict':audit.verdict.value,
        'static_pass':checks.static_pass,'tests_pass':checks.tests_pass,
        'framework_checks':checks.test_count,'generated_tests':checks.generated_count,'exit_status':checks.exit_status,
        'scope':'Restricted fixture source/tests; not arbitrary Python or production certification'}
    resources=[r for r in snapshot.resources if r.experiment_id==spec.experiment_id and r.experiment_version==spec.version]
    for r in resources:
        if 'synthetic' in json.dumps(r.metadata).lower() or 'toy' in str(r.source).lower():
            limitations.append('Resource '+r.resource_id+' is synthetic/toy; population representativeness is not established')
    summary=ResultSummary(run_id=run.run_id,project_id=run.project_id,experiment_id=spec.experiment_id,
        experiment_version=spec.version,hypothesis_id=spec.hypothesis_id,hypothesis_version=spec.hypothesis_version,
        pins=pins,available_evidence_ids=[run.run_id,spec.experiment_id,spec.hypothesis_id,*[m['metric_id'] for m in metrics],*[p['resource_id'] for p in run.input_manifest['dependency_pins']['resource_pins']],impl.implementation_id,audit.review_id],conditions=conditions,metrics=metrics,differences=differences,criteria=criteria,warnings=list(dict.fromkeys(warnings)),
        limitations=list(dict.fromkeys(limitations)),raw_artifact=artifact,
        representative_observations=([i for items in groups.values() for i in items[:2]]+[i for i in raw if i['status']!='success'])[:8],
        implementation_validation=validation,usage=run.environment_metadata.get('usage',{}),actual_cost_usd=run.cost_usd,
        actual_cost_status=run.environment_metadata.get('actual_cost_status','UNKNOWN'))
    if len(summary.model_dump_json())>30000: raise AnalysisError('Result summary bound exceeded')
    return summary
