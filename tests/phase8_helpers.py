"""Offline deterministic preparation/readiness fixtures; no network calls."""
import asyncio
from autolab import schemas as s
from autolab.feasibility.approval import ApprovalService
from autolab.feasibility.capability_registry import CapabilityRegistry
from autolab.feasibility.models import Capability, CostInput, EstimateRange, FeasibilityInputs, ResourceAccess
from autolab.feasibility.service import FeasibilityService
from autolab.preparation.models import AcceptanceCriteria, ResourceRequirement, ResourcePreparationPlan


def seed(ledger, *, approval=True, implementation_scope=True):
    p=ledger.create_project(s.ResearchCharter(project_id='PROJECT_P8',title='Isolated preparation fixture',
        research_question='Does policy A change task success?',objective='Compare matched conditions',
        primary_outcome='Task success',budget_usd=100,max_runtime_minutes=240))
    h=ledger.add_hypothesis(s.Hypothesis(hypothesis_id='HYP_P8',project_id=p.project_id,
        statement='Recovery choice changes task success',falsifiable_prediction='Positive paired task-success contrast'))
    e=ledger.add_experiment_spec(s.ExperimentSpec(experiment_id='EXP_P8',project_id=p.project_id,
        hypothesis_id=h.hypothesis_id,title='Bounded controlled fixture',objective='Compare matched conditions',
        experiment_type='paired controlled fixture',primary_metric='paired task-success difference',
        required_resources=['Task inputs'],required_capabilities=['filesystem_access'],
        controls={'labels':'Reference labels excluded from input','pairing':'Matched task instances across conditions'},
        dataset_requirements={'min_samples':4,'conditions':['A','B'],'schema':['id','text','condition']},
        success_criteria={'support':'Adequate paired interval above zero'},falsification_criteria={'contradiction':'Adequate interval at or below zero'},
        estimated_cost_usd=None,estimated_runtime_minutes=None))
    ledger.add_review(s.ReviewRecord(review_id='ERREV_P8',project_id=p.project_id,target_type='experiments',target_id=e.experiment_id,
        review_type='experiment',verdict='PASS',reviewer_role='critic'))
    registry=CapabilityRegistry([Capability(capability_id='filesystem_access',status='AVAILABLE')])
    inputs=FeasibilityInputs(resource_access=[ResourceAccess(requirement='Task inputs',status='AVAILABLE')],
        costs=[CostInput(category='explicit fixture envelope',unit_price_usd=1,units=EstimateRange(minimum=0,maximum=5))],
        runtime_minutes=EstimateRange(minimum=1,maximum=30),compute_requirements=['Local fixture CPU'],
        storage_gb=EstimateRange(maximum=0.001),warnings=['Offline mechanics fixture, not statistical adequacy proof'])
    FeasibilityService(ledger,registry).assess(p.project_id,e.experiment_id,inputs)
    if approval:
        a=ApprovalService(ledger,allow_test_human=True); packet=a.request_approval(p.project_id,e.experiment_id)
        a.record_human_decision(p.project_id,e.experiment_id,1,'APPROVE',packet_id=packet.packet_id,actor='test-human',
            max_cost_usd=5,max_runtime_minutes=30,approved_actions=['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT'] if implementation_scope else None)
    return p,e,registry


def criteria(**updates):
    return AcceptanceCriteria(required_fields=['id','text','condition'],field_types={'id':'string','text':'string'},
        min_samples=4,unique_fields=['id'],condition_field='condition',required_conditions=['A','B'],
        scientific=['Matched conditions represent the approved contrast; no target answers in inputs'],
        technical=['JSON rows with required fields and at least four inputs'],provenance=['Generator, specification, seed and checksum retained'],**updates)


def requirement(**updates):
    data=[{'id':str(i),'text':text,'condition':'A' if i%2==0 else 'B'} for i,text in enumerate([
        'Find the larger of two counts','Retrieve a named item','Combine disjoint entries','Check an equality constraint'])]
    values=dict(requirement_id='inputs',spec_requirements=['Task inputs'],resource_type='dataset',purpose='Matched task inputs',
        acquisition_mode='SYNTHESIZE',expected_output='JSON task rows',required_capabilities=['filesystem_access'],
        steps=['Serialize outcome-independent declarative rows'],criteria=criteria(),handler='synthetic',
        parameters={'data':data,'specification':'Diverse fixed offline task inputs, no model outputs or results','seed':7},
        estimated_cost_usd=0,estimated_runtime_minutes=0.1)
    values.update(updates); return ResourceRequirement(**values)


class Preparer:
    def __init__(self, requirements=None, *, blocks=(), changes=(), risks=(), mutate=None, responses='ACCEPT'):
        self.requirements=requirements or [requirement()]; self.blocks=list(blocks); self.changes=list(changes); self.risks=list(risks)
        self.mutate=mutate; self.responses=responses; self.calls=0
    async def plan(self, context, assignment, *, previous=None, issues=None):
        self.calls+=1
        from autolab.preparation.models import IssueResponse
        reqs=self.requirements
        if previous:
            reqs=[r.model_copy(update={'parameters':{**r.parameters,'data':requirement().parameters['data']}}) if r.handler=='synthetic' else r for r in previous.resource_requirements]
        plan=ResourcePreparationPlan(**assignment,resource_requirements=reqs,blockers=self.blocks,material_changes=self.changes,additional_risks=self.risks,
            warnings=['Explicit offline fixture, no empirical results'],issue_responses=[IssueResponse(issue_index=i,disposition=self.responses,
                reason='Fix data defect' if self.responses=='ACCEPT' else 'Concise evidence/rebuttal recorded') for i,_ in enumerate(issues or [])])
        return self.mutate(plan) if self.mutate else plan


class Auditor:
    def __init__(self, verdict='PASS', *, sequence=None, mutate=None):
        self.verdict=verdict; self.sequence=list(sequence or []); self.mutate=mutate; self.calls=0
    async def audit(self, context, assignment):
        self.calls+=1; v=self.sequence.pop(0) if self.sequence else self.verdict
        ids=[p['resource_id'] for p in context['resource_pins']]
        report=s.ReadinessReport(**assignment,resource_readiness=True,technical_readiness=True,
            scientific_readiness=v=='PASS',quality_readiness=v=='PASS',verdict=v,
            failed_checks=[] if v=='PASS' else ['Fixture scientific defect'],
            metadata={'semantic_findings':[{'gate':'scientific','resource_ids':ids,'finding':'Controlled mocked independent assessment',
                'evidence':'Bounded fixture review'}], 'issues':[] if v=='PASS' else [{'problem':'Repair fixture','resource_ids':ids}]})
        return self.mutate(report) if self.mutate else report


def run(awaitable): return asyncio.run(awaitable)
