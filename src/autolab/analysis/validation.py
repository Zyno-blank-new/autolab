"""Exact identity checks and conservative, reviewable scientific guard findings."""
import math
import re
from autolab import schemas as s
from .models import AnalysisError, AnalysisOutput


def validate_analysis(output, summary, assignment):
    try: output=AnalysisOutput.model_validate(output.model_dump() if hasattr(output,'model_dump') else output)
    except ValueError: raise AnalysisError('Malformed Analyst structured output') from None
    a=output.analysis
    expected={'project_id':summary.project_id,'experiment_id':summary.experiment_id,
        'experiment_version':summary.experiment_version,'run_id':summary.run_id,
        'hypothesis_id':summary.hypothesis_id,'hypothesis_version':summary.hypothesis_version,**assignment}
    if any(getattr(a,k)!=v for k,v in expected.items()): raise AnalysisError('Analysis identity/version mismatch')
    if a.metric_ids!=[m['metric_id'] for m in summary.metrics] or a.evidence_pins!=summary.pins:
        raise AnalysisError('Analysis metric references/evidence pins mismatch')
    if a.criteria_evaluation!=summary.criteria: raise AnalysisError('Preregistered criteria evaluation changed')
    if len(a.model_dump_json())>22000: raise AnalysisError('Analysis output exceeds character bound')
    for field in ('key_findings','limitations','remaining_uncertainties','unexpected_findings','claims','confounders'):
        if len(getattr(a,field))>8: raise AnalysisError('Analysis '+field+' exceeds eight-item bound')
    if a.recommended_followup: raise AnalysisError('Phase 11 analysis cannot propose executable follow-up work')
    if a.confidence!=0: raise AnalysisError('Quantitative confidence is not computed; retain canonical default 0 as unspecified')
    # Assertions of numeric values must carry real evidence references and supplied values.
    allowed=set(summary.available_evidence_ids)
    for claim in a.claims:
        if not {'claim','evidence_ids','level'}<=set(claim) or claim['level'] not in ('OBSERVATION','INTERPRETATION','GENERALIZATION_LIMIT','EXPLORATORY'):
            raise AnalysisError('Claim requires explicit scientific level and traceable references')
        if not claim['evidence_ids'] or not set(claim['evidence_ids'])<=allowed: raise AnalysisError('Imaginary claim evidence reference')
        if 'values' in claim:
            for key,value in claim['values'].items():
                metric=next((m for m in summary.metrics if m['metric_id']==key),None)
                if not metric or key not in claim['evidence_ids'] or not isinstance(value,(float,int)) or not math.isclose(value,metric['value'],rel_tol=0,abs_tol=1e-12):
                    raise AnalysisError('Numeric claim differs from supplied metric evidence')
    return output


def scientific_findings(analysis, summary, spec):
    """Advisory findings fed to independent Critic. No fabricated critic verdicts.

    The checks cover structured claims and clear phrase violations, not arbitrary
    natural-language entailment. The independent semantic critique remains required.
    """
    findings=[]
    def issue(code,problem,section='interpretation'):
        findings.append({'problem':problem,'severity':'high','section':section,
            'evidence_ids':[summary.run_id,summary.experiment_id,*analysis.metric_ids],
            'why_it_matters':code,'resolution':'Correct the statement using only the supplied descriptive evidence and fixed criteria'})
    text='. '.join([analysis.interpretation,analysis.causal_scope,analysis.generalization_scope,*analysis.key_findings,*analysis.unexpected_findings,
        *analysis.limitations,*analysis.remaining_uncertainties,*[str(c.get('claim','')) for c in analysis.claims],*[str(c.get('evidence','')) for c in analysis.confounders]])
    # Negated limitations do not assert the prohibited claim.
    clauses=re.split(r'(?<!\d)[.!?;\n]|[.!?;\n](?!\d)',text.lower())
    affirmative=[c for c in clauses if not re.search(r'\b(no|not|cannot|doesn.t|without|unavailable|uncomputed|unestablished|neither|avoids?)\b',c)]
    assertion=' '.join(affirmative)
    if re.search(r'\b(proves?|proven|universally|always superior|all populations|general superiority)\b',assertion):
        issue('overgeneralization','Universal/proof language exceeds experiment scope')
    if re.search(r'statistically significant|p[- ]?value|confidence interval|\bpower calculation\b',assertion):
        issue('unsupported_statistics','Inferential statistics were not computed or supplied')
    if re.search(r'\b(causes?|causal|causally)\b',assertion) and not spec.controls.get('pairing'):
        issue('unsupported_causality','Causal attribution is unsupported by this comparison design','causal_scope')
    if analysis.hypothesis_assessment in (s.HypothesisAssessment.SUPPORTED,s.HypothesisAssessment.PARTIALLY_SUPPORTED) and summary.criteria['success_met'] is not True:
        issue('criteria_mismatch','Support conclusion does not meet the fixed success criterion','hypothesis_assessment')
    if summary.criteria['success_met'] is None and analysis.hypothesis_assessment!=s.HypothesisAssessment.INCONCLUSIVE:
        issue('unresolved_criteria','Unknown success criterion requires inconclusive assessment','hypothesis_assessment')
    if summary.warnings and any('incomplete' in w.lower() for w in summary.warnings) and analysis.hypothesis_assessment!=s.HypothesisAssessment.INCONCLUSIVE:
        issue('incomplete_coverage','Incomplete comparison coverage requires inconclusive assessment')
    if not analysis.limitations: issue('missing_limitations','Specific limitations are absent','limitations')
    for metric in summary.metrics:
        if metric['role']=='secondary' and not any(metric['metric_id'] in c.get('evidence_ids',[]) for c in analysis.claims):
            issue('secondary_omitted','Preregistered secondary outcome omitted from material claim evidence','claims')
    if not analysis.claims: issue('missing_trace','Important claims lack structured evidence references','claims')
    if spec.potential_confounders and not set(spec.potential_confounders)<={c.get('confounder') for c in analysis.confounders}:
        issue('missing_confounder','Preregistered confounders are not all assessed','confounders')
    for c in analysis.confounders:
        if c.get('status') not in ('CONTROLLED','POTENTIALLY_ACTIVE','UNKNOWN') or not c.get('evidence'):
            issue('unsupported_confound_control','Confounder status/evidence is missing','confounders')
    if analysis.unexpected_findings and not all('exploratory' in f.lower() for f in analysis.unexpected_findings):
        issue('unlabeled_exploration','Unexpected findings must be labeled exploratory','unexpected_findings')
    if any(c['failure_count'] for c in summary.conditions) and not re.search(r'\bfail\w*|\berrors?\b',text,re.I):
        issue('ignored_failures','Observed failed samples omitted from interpretation')
    # Clear reversed direction, including numeric reversal, is independently detectable.
    for d in summary.differences:
        # A harm hypothesis can predict increasing error. Its support direction
        # is separate from the adapter-declared metric desirability direction.
        quality_direction=d.get('metric_direction') or d['direction']
        delta=(d['intervention_value']-d['control_value']) if 'intervention_value' in d and 'control_value' in d else None
        quality_improvement=(-delta if quality_direction=='lower' else delta if quality_direction=='higher' else None) if delta is not None else d['improvement']
        better=d['intervention'] if (quality_improvement or 0)>0 else d['control']
        worse=d['control'] if better==d['intervention'] else d['intervention']
        if d['direction'] and re.search(r'\b'+re.escape(worse)+r'\b[^.!?]{0,35}\b(better|superior|lower error)\b',assertion):
            issue('wrong_direction','Metric interpretation reverses the supplied direction')
        if quality_direction=='lower':
            high=max(d['control_value'],d['intervention_value']);low=min(d['control_value'],d['intervention_value'])
            match=re.search(r'(\d+(?:\.\d+)?)\s+(?:is\s+)?(?:better|superior)\s+(?:than\s+)?(\d+(?:\.\d+)?)',text)
            if match and math.isclose(float(match[1]),high,abs_tol=1e-12) and math.isclose(float(match[2]),low,abs_tol=1e-12) and high>low:
                issue('wrong_direction','Larger value described as better for lower-is-better metric')
    def numbers(value):
        if isinstance(value,(int,float)) and not isinstance(value,bool): return [float(value)]
        if isinstance(value,dict): return [x for k,v in value.items() if not k.endswith('fingerprint') and 'sha256' not in k for x in numbers(v)]
        if isinstance(value,list): return [x for v in value for x in numbers(v)]
        if isinstance(value,str): return [float(n) for n in re.findall(r'(?<![\w])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w])',value)]
        return []
    supplied=numbers(summary.model_dump())+numbers(spec.model_dump())
    for n in re.findall(r'(?<![\w])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w])',text):
        if not any(math.isclose(float(n),v,rel_tol=1e-10,abs_tol=1e-12) for v in supplied):
            issue('unsupported_number','Numeric claim '+n+' is absent from supplied evidence');break
    return findings[:8]


def validate_review(batch, assignment, analysis, summary, findings):
    from autolab.hypotheses.models import ReviewBatch
    try: batch=ReviewBatch.model_validate(batch.model_dump() if hasattr(batch,'model_dump') else batch)
    except ValueError: raise AnalysisError('Malformed Scientific Critic output') from None
    if len(batch.reviews)!=1: raise AnalysisError('Exactly one analysis review required')
    r=batch.reviews[0]
    if (r.review_id,r.project_id,r.target_id,r.target_version,r.reviewer_role,r.review_type,r.target_type)!=(assignment['review_id'],summary.project_id,analysis.analysis_id,analysis.version,'critic','analysis','analyses'):
        raise AnalysisError('Critic review identity/version mismatch')
    if r.verdict not in (s.ReviewVerdict.PASS,s.ReviewVerdict.REVISE,s.ReviewVerdict.REJECT): raise AnalysisError('Unsupported result critique verdict')
    if len(r.issues)>8 or len(r.questions)>5 or len(r.recommendations)>5 or len(r.model_dump_json())>18000: raise AnalysisError('Critic output bound exceeded')
    allowed={*summary.available_evidence_ids,analysis.analysis_id}
    if r.verdict!=s.ReviewVerdict.PASS and not r.issues: raise AnalysisError('Non-PASS requires concrete critique')
    for issue in r.issues:
        if not all(issue.get(k) for k in ('problem','severity','section','evidence_ids','why_it_matters','resolution')):
            raise AnalysisError('Critique missing material issue fields')
        if not set(issue['evidence_ids'])<=allowed: raise AnalysisError('Critic invented evidence')
    if r.verdict==s.ReviewVerdict.PASS and (findings or any(i.get('severity') in ('high','critical') for i in r.issues)):
        raise AnalysisError('PASS cannot authorize unresolved deterministic/material findings')
    return r


def validate_responses(responses, review, summary):
    expected={(review.review_id,i) for i in range(len(review.issues))}
    if len(responses)!=len(expected) or {(r.review_id,r.issue_index) for r in responses}!=expected:
        raise AnalysisError('Respond exactly once to every material critique')
    allowed=set(summary.available_evidence_ids)
    if any(not set(r.evidence_ids)<=allowed for r in responses): raise AnalysisError('Response cites imaginary evidence')
    if any(r.disposition=='REBUT' and not r.evidence_ids for r in responses): raise AnalysisError('Rebuttal requires evidence')
