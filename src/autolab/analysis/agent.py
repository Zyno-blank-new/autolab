"""Scientific interpretation uses Omnigent; arithmetic stays in ResultSummary."""
import json
from autolab.config import PROJECT_ROOT
from autolab.planner.service import OmnigentPlanner
from .models import AnalysisOutput, AnalysisError

def analysis_output_schema():
    schema=AnalysisOutput.model_json_schema()
    a=schema['$defs']['ScientificAnalysis']['properties']
    for name in ('key_findings','limitations','remaining_uncertainties','unexpected_findings','claims','confounders'):
        a[name]['maxItems']=8
    a['recommended_followup']['maxItems']=0
    a['confidence']={'type':'number','const':0}
    return schema

class OmnigentAnalysisAgent:
    def __init__(self, *, timeout_seconds=240, model=None):
        self.transport=OmnigentPlanner(timeout_seconds=timeout_seconds,model=model)

    @property
    def calls(self): return self.transport.calls

    async def interpret(self, context, assignment, *, previous=None, review=None):
        payload={'stage':'revision' if previous else 'analysis','scientific_context':context,
            'assignment':assignment,'output_schema':analysis_output_schema(),
            'previous':previous.model_dump(mode='json') if previous else None,
            'review':review.model_dump(mode='json') if review else None,
            'instructions':'Return canonical ScientificAnalysis in analysis plus responses. Exact assigned analysis_id/version and all summary identity/pins/metric_ids. criteria_evaluation must equal ResultSummary.criteria verbatim. confidence=0 means UNSPECIFIED, not computed probability. recommended_followup=[]; Planner alone owns next action. Every material claim needs claims entries with claim, level (OBSERVATION/INTERPRETATION/GENERALIZATION_LIMIT/EXPLORATORY), evidence_ids (only IDs in ResultSummary.available_evidence_ids). Optional values maps metric IDs to exact supplied numbers. Compare fixed success AND falsification criteria. Cover every preregistered confounder using confounder/status CONTROLLED/POTENTIALLY_ACTIVE/UNKNOWN/evidence. At most eight items each in key_findings, limitations, remaining_uncertainties, unexpected_findings, claims, confounders. Keep analysis prose under 12000 characters. Limitations specific to supplied state. No fake statistics, invented numbers, causal overreach, universal claims, or new metrics. Include all secondary findings, failures and denominator limitations. unexpected_findings optional and labeled exploratory. Omit created_at. If revision: respond to every issue via review_id/issue_index/disposition ACCEPT/REBUT/CLARIFY/reason/evidence_ids; preserve supported rebuttals. Maximum one revision.'}
        prompt=json.dumps(payload,allow_nan=False)
        if len(prompt)>90000: raise AnalysisError('Analyst context bound exceeded')
        raw=await self.transport.invoke_agent(PROJECT_ROOT/'agents/analyst/analyst.yaml',prompt,
            project_id=context['charter']['project_id'],role='analyst')
        if len(raw)>30000: raise AnalysisError('Analyst response bound exceeded')
        try: return AnalysisOutput.model_validate_json(raw)
        except ValueError: raise AnalysisError('Malformed Analyst structured output') from None
