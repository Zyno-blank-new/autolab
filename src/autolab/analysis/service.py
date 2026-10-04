"""Valid results → analysis → independent critique → one revision → PI boundary."""
from autolab import schemas as s
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import current_run, current_analysis, selected_experiment, latest_review
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.budget import calculate_budget
from autolab.preparation.manifest import fingerprint
from autolab.planner.service import runtime_metadata
from autolab.hypotheses.agent import OmnigentScientificCritic
from .agent import OmnigentAnalysisAgent
from .models import AnalysisError, AnalysisResult
from .result_summary import build_result_summary
from .validation import validate_analysis, scientific_findings, validate_review, validate_responses
from .persistence import analysis_current

class AnalysisService:
    def __init__(self, ledger, agent=None, critic=None):
        self.ledger=ledger
        self.agent=agent if agent is not None else OmnigentAnalysisAgent()
        self.critic=critic if critic is not None else OmnigentScientificCritic()

    def _snapshot(self,project,target='analyst'):
        snapshot=load_snapshot(self.ledger,project)
        gate=s.NextDecision(decision_id='DEC_ANALYSIS_GATE',project_id=project,action='ANALYZE_RESULT',target_agent=target,
            reason='Verify exact analysis prerequisites',remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd)
        valid=DecisionValidator().validate(gate,snapshot)
        if not valid.valid: raise AnalysisError('Analysis blocked: '+'; '.join(valid.reasons))
        return snapshot

    def _event(self,project,kind,analysis=None,*,payload=None,critic=False):
        data=dict(payload or {})
        metadata=runtime_metadata(self.critic if critic else self.agent)
        if metadata and kind in ('SCIENTIFIC_ANALYSIS_CREATED','SCIENTIFIC_ANALYSIS_REVISED','RESULT_CRITIQUE_PASSED','RESULT_CRITIQUE_REJECTED','RESULT_ANALYSIS_REVISION_REQUESTED'):
            data['model_metadata']=metadata
        return s.EventRecord(event_id=self.ledger.next_id('EVENT'),project_id=project,event_type=kind,
            actor='critic' if critic else 'analyst',target_type='analyses' if analysis else None,
            target_id=analysis.analysis_id if analysis else None,summary=kind+'; scientific evidence preserved; Planner owns next action',payload=data)

    def _commit(self, project, records, baseline, summary):
        def check():
            fresh=self._snapshot(project)
            if build_result_summary(fresh).pins!=summary.pins: raise AnalysisError('Evidence changed while reasoning')
            for field in ('charter','authorized_scope','hypotheses','experiments','runs','metrics','implementations','resources','readiness','reviews','analyses','decisions'):
                if getattr(fresh,field)!=getattr(baseline,field): raise AnalysisError('Concurrent scientific state changed; rebuild analysis')
        self.ledger.add_many(records,check=check)
        return self._snapshot(project)

    @staticmethod
    def _context(snapshot,summary):
        spec=selected_experiment(snapshot)
        h=next(h for h in snapshot.hypotheses if (h.hypothesis_id,h.version)==(spec.hypothesis_id,spec.hypothesis_version))
        run=current_run(snapshot)
        impl=next(i for i in snapshot.implementations if i.implementation_id==run.implementation_id)
        context={'charter':snapshot.charter.model_dump(mode='json'),'hypothesis':h.model_dump(mode='json'),
            'authorized_research_scope':snapshot.authorized_scope.model_dump(mode='json') if snapshot.authorized_scope else None,
            'authorized_analysis_charter':next((e.payload.get('analysis_charter') for e in reversed(snapshot.events) if e.event_type=='RESULT_INTERPRETATION_AUTHORIZED' and e.actor=='test_human'),None),
            'experiment_spec':spec.model_dump(mode='json'),'result_summary':summary.model_dump(mode='json'),
            'implementation_declared_planning_notes':impl.metadata.get('plan',{}).get('limitations',[]),
            'temporal_context':'ImplementationPlan notes were written before execution; actual completed run and pinned validation receipts establish current result/validation state. Evaluate exact preregistered criteria against this completed run without inventing another future temporal requirement. Planning promises are not fresh validation, runtime failures or observations.',
            'run_metadata':{'run_id':run.run_id,'status':run.status.value,'random_seed':run.random_seed,
                'started_at':run.started_at.isoformat(),'completed_at':run.completed_at.isoformat(),
                'implementation_id':run.implementation_id,'implementation_hash':impl.code_version,
                'python_version':run.environment_metadata.get('python_version'),
                'duration_seconds':run.environment_metadata.get('duration_seconds'),'error_message':run.error_message},
            'resource_limits':[{'id':r.resource_id,'source':r.source,'metadata':{k:v for k,v in r.metadata.items() if k in ('acquisition_mode','generator','specification','intended_role','note')}} for r in snapshot.resources if r.experiment_id==spec.experiment_id][:8],
            'prior_critic_findings':[{'review_id':r.review_id,'target_id':r.target_id,'target_version':r.target_version,'verdict':r.verdict.value,'issues':r.issues[:3]}
                for r in snapshot.reviews if r.target_id in (spec.experiment_id,h.hypothesis_id)][-4:]}
        import json
        if len(json.dumps(context))>55000: raise AnalysisError('Scientific context exceeds bound')
        return context

    async def analyze(self,project):
        snapshot=self._snapshot(project)
        if current_analysis(snapshot): raise AnalysisError('Existing analysis must be critiqued; do not silently generate another')
        summary=build_result_summary(snapshot)
        context=self._context(snapshot,summary)
        self.ledger.add_event(self._event(project,'RESULT_ANALYSIS_STARTED',payload={'run_id':summary.run_id,'result_summary':summary.model_dump(mode='json')}))
        try:
            assignment={'analysis_id':self.ledger.next_id('ANALYSIS'),'version':1}
            # Repeat integrity immediately before any model call.
            if build_result_summary(self._snapshot(project)).pins!=summary.pins: raise AnalysisError('Evidence became stale')
            out=validate_analysis(await self.agent.interpret(context,assignment),summary,assignment)
            if out.responses: raise AnalysisError('Initial analysis cannot contain unsolicited responses')
            a=out.analysis.model_copy(update={'created_at':s.utc_now()})
            findings=scientific_findings(a,summary,selected_experiment(snapshot))
            event=self._event(project,'SCIENTIFIC_ANALYSIS_CREATED',a,payload={'version':a.version,
                'analysis_fingerprint':fingerprint(a),'result_summary':summary.model_dump(mode='json'),'deterministic_guard_findings':findings})
            self._commit(project,[a,event],snapshot,summary)
            return a
        except Exception:
            self.ledger.add_event(self._event(project,'RESULT_ANALYSIS_FAILED'))
            raise

    async def critique(self,project):
        snapshot=self._snapshot(project,'critic')
        a=current_analysis(snapshot)
        if not analysis_current(snapshot,a): raise AnalysisError('Analysis is stale/untrusted')
        if latest_review(snapshot,s.ScientificAnalysis,a.analysis_id,a.version,'analysis'):
            raise AnalysisError('Analysis version already reviewed; bounded workflow cannot restart')
        summary=build_result_summary(snapshot)
        context=self._context(snapshot,summary)
        self.ledger.add_event(self._event(project,'RESULT_CRITIQUE_STARTED',a,critic=True))
        try:
            r,snapshot=await self._review(project,snapshot,context,summary,a)
            reviews=[r.review_id];rounds=0
            if r.verdict==s.ReviewVerdict.REVISE and a.version==1:
                assignment={'analysis_id':a.analysis_id,'version':2}
                if not analysis_current(self._snapshot(project),a): raise AnalysisError('Analysis stale before revision')
                out=validate_analysis(await self.agent.interpret(context,assignment,previous=a,review=r),summary,assignment)
                validate_responses(out.responses,r,summary)
                revised=out.analysis.model_copy(update={'created_at':s.utc_now()})
                event=self._event(project,'SCIENTIFIC_ANALYSIS_REVISED',revised,payload={'version':2,
                    'analysis_fingerprint':fingerprint(revised),'result_summary':summary.model_dump(mode='json'),
                    'responses':[response.model_dump(mode='json') for response in out.responses]})
                snapshot=self._commit(project,[revised,event],snapshot,summary)
                a=revised;rounds=1
                r,snapshot=await self._review(project,snapshot,context,summary,a,responses=out.responses)
                reviews.append(r.review_id)
            result=AnalysisResult(analysis_id=a.analysis_id,version=a.version,review_ids=reviews,revision_rounds=rounds,verdict=r.verdict.value)
            self._commit(project,[self._event(project,'RESULT_ANALYSIS_COMPLETED',a,payload=result.model_dump(mode='json'))],snapshot,summary)
            return result
        except Exception:
            self.ledger.add_event(self._event(project,'RESULT_CRITIQUE_FAILED',a,critic=True))
            raise

    async def _review(self,project,snapshot,context,summary,a, responses=None):
        self._snapshot(project,'critic')
        if not analysis_current(load_snapshot(self.ledger,project),a): raise AnalysisError('Evidence changed before critique')
        findings=scientific_findings(a,summary,selected_experiment(snapshot))
        assignment={'review_id':self.ledger.next_id('HREV'),'project_id':project,'target_id':a.analysis_id,'target_version':a.version}
        batch=await self.critic.review_analysis(context,a,assignment,findings=findings,responses=responses)
        r=validate_review(batch,assignment,a,summary,findings)
        r=r.model_copy(update={'created_at':s.utc_now(),'metadata':{'analysis_fingerprint':fingerprint(a),
            'evidence_pins':summary.pins,'deterministic_guard_findings':findings}})
        kind={s.ReviewVerdict.PASS:'RESULT_CRITIQUE_PASSED',s.ReviewVerdict.REVISE:'RESULT_ANALYSIS_REVISION_REQUESTED',s.ReviewVerdict.REJECT:'RESULT_CRITIQUE_REJECTED'}[r.verdict]
        snapshot=self._commit(project,[r,self._event(project,kind,a,critic=True,payload={'review_id':r.review_id,'version':a.version,'verdict':r.verdict.value})],snapshot,summary)
        return r,snapshot

    async def run(self,project,*,critique_only=False):
        if not critique_only: await self.analyze(project)
        return await self.critique(project)
