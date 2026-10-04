"""Offline, explicitly synthetic research choices; services remain production code."""
from autolab import schemas as s
from autolab.orchestration.state_machine import selected_experiment
from autolab.experiment_design.models import CandidateBatch
from autolab.experiment_design.validation import SPEC_FIELDS
from autolab.hypotheses.models import ReviewBatch

class Planner:
    def __init__(self, actions): self.actions=list(actions);self.calls=0;self.contexts=[]
    async def propose(self, context, decision_id, feedback=None):
        self.calls+=1;self.contexts.append(context)
        action=self.actions.pop(0)
        target={'RUN_FOLLOWUP':'experiment_designer','DESIGN_EXPERIMENT':'experiment_designer',
            'SELECT_EXPERIMENT':'planner','GATHER_EVIDENCE':'evidence','REFINE_HYPOTHESIS':'hypothesis',
            'GENERATE_HYPOTHESES':'hypothesis','ACCEPT_HYPOTHESIS':'planner','REJECT_HYPOTHESIS':'planner',
            'STOP':None,'PREPARE_RESOURCES':'preparation','IMPLEMENT_EXPERIMENT':'implementer',
            'RUN_EXPERIMENT':'experiment_runner','ANALYZE_RESULT':'analyst'}[action]
        ids=[context.summaries['candidates'][-2]['id']] if action=='SELECT_EXPERIMENT' else []
        result=context.current_records.get('reviewed_result',{})
        reason='Reduce boundary-crossing uncertainty identified in '+str(result.get('parent_analysis_id'))+'; compare an independently frozen in-range cohort to distinguish clipping activation from universal benefit. The observed first MAE decrease alone cannot generalize.'
        if action=='STOP':reason='Current reviewed measurements resolve the fixed-input charter; further work has low decision value, retain limited scope and stop.'
        return s.NextDecision(decision_id=decision_id,project_id=context.charter.project_id,action=action,
            target_agent=target,required_context_ids=ids,reason=reason,
            remaining_budget_usd=context.budget.remaining_budget_usd).model_dump_json()

class Designer:
    def __init__(self, spec):self.spec=spec;self.contexts=[]
    async def generate(self, context, assignments):
        self.contexts.append(context)
        rows=[]
        for i,assignment in enumerate(assignments):
            design={k:getattr(self.spec,k) for k in SPEC_FIELDS}
            design['success_criteria']={'comparison':{'control':'baseline','intervention':'clipped','direction':'lower','minimum_improvement':0}}
            design['falsification_criteria']={'comparison':{'maximum_improvement':0}}
            design['dataset_requirements']={**design['dataset_requirements'],'cohort': 'in_range_negative_control' if i==0 else 'boundary_stress_test'}
            design.update(metric_rationale='Same preregistered error unit discriminates activation mechanism',
                sampling_strategy='Four independently frozen rows in each proposed cohort; no post-result tuning',
                expected_result_patterns={'supported':'Condition difference in new cohort','contradicted':'No condition difference','inconclusive':'Insufficient coverage'},
                inconclusive_criteria='Missing paired sample coverage prevents interpretation')
            rows.append(s.ExperimentCandidate(**assignment,title='Boundary mechanism test '+str(i),
                objective='Test clipping activation on independent cohort '+str(i),
                approach='Frozen in-range negative control' if i==0 else 'Frozen boundary stress test',design=design,
                expected_information_gain=.5,feasibility_score=.8,major_risks=['Synthetic sample scope'],
                estimated_cost_usd=0,estimated_runtime_minutes=1))
        return CandidateBatch(candidates=rows)

class DesignCritic:
    async def review_experiments(self,context,candidates,assignments,**kwargs):
        return ReviewBatch(reviews=[s.ReviewRecord(**a,review_type='experiment',target_type='experiment_candidates',
            reviewer_role='critic',verdict='PASS') for a in assignments])
