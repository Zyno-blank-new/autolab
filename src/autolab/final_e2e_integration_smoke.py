"""Explicit paid final-demo integration over real services and Omnigent agents.

Without --test-human this stops at approval. Test approval is never implicit.
No scripted scientific decisions, verdicts, code, measurements or interpretations.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from autolab import schemas as s
from autolab.config import configure, PROJECT_ROOT
from autolab.final_demo import PROJECT, create_demo, require_demo, supported_spec, test_contract, FinalDemoAdapter, operator_catalog
from autolab.ledger import ResearchLedger
from autolab.planner.service import OmnigentPlanner
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import (derive_control_state, selected_experiment,
    current_implementation, approval_for)
from autolab.orchestration.models import ApprovalScope, ControlStage
from autolab.orchestration.models import ContextLimits
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.budget import calculate_time
from autolab.feasibility.capability_registry import CapabilityRegistry
from autolab.feasibility.models import FeasibilityInputs, ResourceAccess, CostInput, EstimateRange
from autolab.feasibility.service import FeasibilityService
from autolab.feasibility.approval import ApprovalService, render_packet
from autolab.feasibility.persistence import spec_fingerprint, current_packet
from autolab.literature.agent import OmnigentEvidenceAgent
from autolab.literature.models import LiteratureLimits
from autolab.literature.service import EvidencePipeline
from autolab.hypotheses.agent import OmnigentHypothesisAgent, OmnigentScientificCritic
from autolab.hypotheses.models import HypothesisLimits
from autolab.hypotheses.service import HypothesisPipeline
from autolab.experiment_design.agent import OmnigentExperimentDesigner
from autolab.experiment_design.service import ExperimentDesignPipeline
from autolab.preparation.agent import OmnigentPreparationAgent
from autolab.preparation.service import PreparationService
from autolab.readiness.agent import OmnigentReadinessAuditor
from autolab.readiness.service import ReadinessService
from autolab.implementation.agent import OmnigentImplementer, OmnigentCodeAuditor
from autolab.implementation.service import ImplementationService
from autolab.implementation.persistence import audited_implementation_passes
from autolab.analysis.agent import OmnigentAnalysisAgent
from autolab.analysis.service import AnalysisService
from autolab.runtime.service import ExperimentRuntime
from autolab.runtime.adapters import ScalarFixtureAdapter
from autolab.reporting.service import ReportService
from autolab.reporting.view import build_view, render_status
from autolab.reporting.public import public
from autolab.event_stream import EventStream


class ObservedTransport(OmnigentPlanner):
    """Record timing/configuration outside the scientific commit windows."""
    def __init__(self, path, *, cap=40):
        super().__init__(timeout_seconds=420)
        self.path = path
        self.cap = cap
        self.receipts = json.loads(path.read_text()) if path.exists() else []
        self.on_events = None

    async def invoke_agent(self, agent_path, prompt, *, project_id, role):
        if self.on_events:
            self.on_events()
        self.receipts = json.loads(self.path.read_text()) if self.path.exists() else []
        if len(self.receipts) >= self.cap:
            raise RuntimeError('Explicit final integration model-call cap reached; no additional invocation.')
        receipt = {'index':len(self.receipts)+1, 'role':role, 'project_id':project_id,
            'started_at':s.utc_now().isoformat(), 'status':'STARTED'}
        self.receipts.append(receipt)
        self.path.write_text(json.dumps(self.receipts, indent=2)+'\n')
        start = time.monotonic()
        print(f'OMNIGENT {role}: actual invocation {receipt["index"]}', flush=True)
        try:
            result = await super().invoke_agent(agent_path, prompt, project_id=project_id, role=role)
            receipt['status'] = 'COMPLETED'
            return result
        except Exception as error:
            receipt.update(status='FAILED', error_type=type(error).__name__)
            raise
        finally:
            receipt.update(completed_at=s.utc_now().isoformat(), duration_seconds=time.monotonic()-start,
                configuration=self.last_model_metadata)
            self.path.write_text(json.dumps(self.receipts, indent=2)+'\n')

    def flush(self, ledger):
        self.receipts = json.loads(self.path.read_text()) if self.path.exists() else []
        existing = {e.payload.get('index') for e in ledger.list_events(PROJECT)
            if e.event_type == 'DEMO_MODEL_INVOCATION'}
        for receipt in self.receipts:
            if receipt['index'] in existing or receipt['status'] == 'STARTED':
                continue
            ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'), project_id=PROJECT,
                event_type='DEMO_MODEL_INVOCATION', actor='demo_observer',
                summary=f'Actual Omnigent {receipt["role"]} invocation {receipt["status"]}; timing/configuration receipt only',
                payload=receipt))


def observed(agent, transport):
    # Keep each role's last invocation metadata independent while sharing the
    # sequential demo's durable call journal and global cap.
    agent.transport = ObservedTransport(transport.path, cap=transport.cap)
    agent.transport.on_events = transport.on_events
    return agent


def request_packet(ledger, *, refresh=False, preparation_proposal=None):
    snapshot = load_snapshot(ledger, PROJECT)
    spec = selected_experiment(snapshot)
    supported_spec(spec)
    if current_packet(snapshot) and not refresh:
        return current_packet(snapshot)
    registry = CapabilityRegistry.local(PROJECT_ROOT)
    remaining=calculate_time(snapshot).remaining_minutes
    planning_limit=min(20,remaining-1) if remaining is not None else 20
    if planning_limit<.1:
        raise ValueError('Charter time exhausted; preserve checkpoint and obtain an explicitly authorized new scope, never reset the charter.')
    from autolab.preparation.manifest import current_plan
    preparation_plan=preparation_proposal or current_plan(snapshot)
    inputs = FeasibilityInputs(
        resource_access=[ResourceAccess(requirement=r, status='AVAILABLE',
            notes=['Exact frozen rows are already declared in the reviewed spec; installed CPU worker is validated by the baseline tests. Operator input serialization follows approval; independent readiness remains mandatory.']) for r in spec.required_resources],
        costs=[CostInput(category='Remaining Omnigent reasoning calls; billing unavailable',
            units=EstimateRange(minimum=0,maximum=20),unit_price_usd=None)],
        runtime_minutes=EstimateRange(minimum=.1,maximum=planning_limit),
        runtime_assumptions=['Remaining bounded local protocol and reasoning/audits planned within the lesser of twenty minutes and current charter time minus a one-minute margin; an estimate and approval limit, not observed timing or a provider timeout guarantee'],
        compute_requirements=['Local CPU; no external subject inference'],
        execution_risks=preparation_plan.additional_risks if preparation_plan else [],
        user_input_required=(preparation_plan.blockers+preparation_plan.user_input_required+preparation_plan.material_changes) if preparation_proposal else [],
        warnings=['Tiny synthetic protocol; no population efficacy or significance claim; actual model billing UNKNOWN'])
    FeasibilityService(ledger,registry).assess(PROJECT,spec.experiment_id,inputs)
    return ApprovalService(ledger).request_approval(PROJECT,spec.experiment_id)


def test_approve(ledger, packet, *, explicit_test_human=False):
    if not explicit_test_human:
        raise ValueError('Packet approval requires explicit isolated test-human authorization.')
    ApprovalService(ledger,allow_test_human=True).record_human_decision(PROJECT,packet.experiment_id,
        packet.experiment_version,'APPROVE',packet_id=packet.packet_id,actor='test-human',
        max_cost_usd=20,max_runtime_minutes=packet.assessment.runtime_minutes.maximum,acknowledge_unknowns=True,
        approved_actions=['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT'],
        note='Explicit --test-human automated isolated final audit; unknown billing acknowledged; exact packet scope only')


def test_authorize_run(ledger, record, *, explicit_test_human=False):
    if not explicit_test_human:
        raise ValueError('Exact scientific run scope requires explicit test-human integration authorization.')
    snapshot=load_snapshot(ledger,PROJECT)
    if not audited_implementation_passes(snapshot,record):
        raise ValueError('Independent exact code audit and deterministic tests required before run scope.')
    if approval_for(snapshot,s.PlannerAction.RUN_EXPERIMENT):
        return
    prior=approval_for(snapshot,s.PlannerAction.IMPLEMENT_EXPERIMENT)
    if not prior:
        raise ValueError('Current exact implementation approval missing.')
    scope=ApprovalScope.model_validate({**prior.model_dump(mode='json'),
        'approved_actions':['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT','RUN_EXPERIMENT'],
        'implementation_id':record.implementation_id,
        'note':'Explicit --test-human isolated final audit: exact audited implementation; offline one-run CPU contract; no production authorization'})
    ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'),project_id=PROJECT,
        event_type='HUMAN_APPROVED',actor='test-human',target_type='experiments',target_id=record.experiment_id,
        summary='Explicit isolated exact implementation execution scope',payload=scope.model_dump(mode='json')))


async def run(path, *, explicit_test_human=False, max_actions=20, cap=40, stop_at_approval=False, recover_design_review=False, refresh_feasibility=False):
    configure()
    path=require_demo(path)
    root=path.parent
    with ResearchLedger(path) as ledger:
        transport=ObservedTransport(root/'model_calls.json',cap=cap)
        event_stream=EventStream(PROJECT,root/'process.log')
        transport.on_events=lambda:event_stream.refresh(ledger)
        critic=observed(OmnigentScientificCritic(),transport)
        services={
            'evidence':EvidencePipeline(ledger,observed(OmnigentEvidenceAgent(),transport),
                limits=LiteratureLimits(query_count=2,results_per_query_provider=3,max_raw_candidates=12,top_k=2)),
            'hypothesis':HypothesisPipeline(ledger,observed(OmnigentHypothesisAgent(),transport),critic,
                limits=HypothesisLimits(candidate_count=2)),
            'design':ExperimentDesignPipeline(ledger,observed(OmnigentExperimentDesigner(),transport),critic),
            'preparation':PreparationService(ledger,observed(OmnigentPreparationAgent(),transport),root=root),
            'readiness':ReadinessService(ledger,observed(OmnigentReadinessAuditor(),transport)),
            'implementation':ImplementationService(ledger,observed(OmnigentImplementer(),transport),
                observed(OmnigentCodeAuditor(),transport),root=root),
            'runtime':ExperimentRuntime(ledger,root=root),
            'analysis':AnalysisService(ledger,observed(OmnigentAnalysisAgent(),transport),critic),
        }
        if any(e.event_type=='PREPARATION_PLAN_CREATED' and e.payload.get('successor_proposal_id')
               for e in ledger.list_events(PROJECT)):
            from autolab.final_demo import RecoveryResourceValidator
            services['readiness'].validators.register(RecoveryResourceValidator(root))
        control=Orchestrator(ledger,transport,context_builder=ContextBuilder(
            ContextLimits(summary_chars=160,records_per_kind=4,recent_decisions=4,
                recent_events=4,max_json_chars=32000)))
        post_result_actions=0
        try:
            if recover_design_review:
                before=load_snapshot(ledger,PROJECT)
                decision=before.decisions[-1] if before.decisions else None
                failed=next((e for e in reversed(before.events) if e.event_type=='ADAPTIVE_SPECIALIST_FAILED'
                    and decision and e.payload.get('decision_id')==decision.decision_id),None)
                if not failed or decision.action!=s.PlannerAction.DESIGN_EXPERIMENT:
                    raise ValueError('Review reconciliation requires the preserved failed design dispatch.')
                started=s.utc_now(); clock=time.monotonic()
                result=await services['design'].review_existing(PROJECT)
                ledger.add_many([s.EventRecord(event_id=ledger.next_id('EVENT'),project_id=PROJECT,
                    event_type=kind,actor='orchestrator',target_type='decisions',target_id=decision.decision_id,
                    summary='Explicit review-only reconciliation completed; original failure retained; no generation repeated',
                    payload={'decision_id':decision.decision_id, 'role':'experiment_designer',
                        **result.model_dump(mode='json')}) for kind in ('SPECIALIST_COMPLETED','ADAPTIVE_CONTROL_RETURNED')])
                ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'),project_id=PROJECT,
                    event_type='DEMO_ACTION_TIMING',actor='demo_observer',summary='Measured explicit review-only reconciliation',
                    payload={'started_at':started.isoformat(),'completed_at':s.utc_now().isoformat(),
                        'duration_seconds':time.monotonic()-clock,'decision_ids':[decision.decision_id], 'status':'RECONCILED'}))
                transport.flush(ledger)
                event_stream.refresh(ledger)
            for _ in range(max_actions):
                snapshot=load_snapshot(ledger,PROJECT)
                state=derive_control_state(snapshot)
                print(public(render_status(build_view(ledger,PROJECT))),flush=True)
                if state in (ControlStage.COMPLETED,ControlStage.PAUSED,ControlStage.RUNNING,ControlStage.BLOCKED):
                    break
                spec=selected_experiment(snapshot)
                if spec:
                    supported_spec(spec)
                    if not approval_for(snapshot,s.PlannerAction.PREPARE_RESOURCES):
                        packet=request_packet(ledger,refresh=refresh_feasibility)
                        refresh_feasibility=False
                        print(public(render_packet(packet)),flush=True)
                        if not explicit_test_human or stop_at_approval:
                            print('HUMAN ACTION REQUIRED: inspect and explicitly approve the exact packet.',flush=True)
                            break
                        test_approve(ledger,packet,explicit_test_human=explicit_test_human)
                        snapshot=load_snapshot(ledger,PROJECT)
                    services['preparation'].catalog=operator_catalog(root,spec)
                    if snapshot.readiness and snapshot.readiness[-1].verdict=='PASS':
                        contract=test_contract(spec,snapshot)
                        services['implementation'].contracts[spec_fingerprint(spec)]=contract
                        services['runtime'].adapters[spec_fingerprint(spec)]=FinalDemoAdapter(spec_fingerprint(spec))
                    record=current_implementation(snapshot)
                    if record and audited_implementation_passes(snapshot,record) and not snapshot.runs:
                        if not explicit_test_human:
                            print('HUMAN ACTION REQUIRED: exact implementation RUN scope is separate from packet approval.',flush=True)
                            break
                        test_authorize_run(ledger,record,explicit_test_human=explicit_test_human)
                # Resume through the existing pending-decision and once-only checks.
                action_started=s.utc_now()
                action_clock=time.monotonic()
                result=await control.continue_research(PROJECT,max_steps=1,services=services)
                action_completed=s.utc_now()
                ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'),project_id=PROJECT,
                    event_type='DEMO_ACTION_TIMING',actor='demo_observer',
                    summary='Observed bounded control/specialist wall time; excludes time outside this invocation',
                    payload={'started_at':action_started.isoformat(),'completed_at':action_completed.isoformat(),
                        'duration_seconds':time.monotonic()-action_clock,'decision_ids':result['decisions'],
                        'status':result['status']}))
                transport.flush(ledger)
                print(f'CONTROL {result["status"]}; actual decisions {result["decisions"]}',flush=True)
                after=load_snapshot(ledger,PROJECT)
                if snapshot.analyses and result['decisions']:
                    post_result_actions+=1
                    if post_result_actions>=2:
                        break  # One specialist action, then its next PI boundary; never force a follow-up.
                if result['status']=='RECONCILIATION_REQUIRED':
                    break
            transport.flush(ledger)
            event_stream.refresh(ledger)
            report=ReportService(ledger).generate(PROJECT)
            summary={'project_id':PROJECT,'db':str(path.relative_to(PROJECT_ROOT)),
                'report':str(Path(report['path']).relative_to(PROJECT_ROOT)),
                'state':build_view(ledger,PROJECT)['state'],'snapshot':load_snapshot(ledger,PROJECT).model_dump(mode='json'),
                'model_calls':transport.receipts,'explicit_test_human':explicit_test_human}
            (root/'summary.json').write_text(json.dumps(public(summary),indent=2)+'\n')
            return summary
        except Exception as error:
            transport.flush(ledger)
            event_stream.refresh(ledger)
            # A truthful partial report is useful; no successful substitute response.
            ReportService(ledger).generate(PROJECT)
            (root/'failure.json').write_text(json.dumps({'error_type':type(error).__name__,
                'public_error':public(str(error)), 'state':build_view(ledger,PROJECT)['state']},indent=2)+'\n')
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,help='Explicit demo.db; omission creates a fresh charter-only namespace.')
    parser.add_argument('--test-human',action='store_true',help='Explicit automated isolated-test packet and exact implementation run approval; never production authority.')
    parser.add_argument('--stop-at-approval',action='store_true',help='Persist a reviewable packet and halt even in test mode.')
    parser.add_argument('--recover-design-review',action='store_true',help='Explicitly reconcile an unreviewed persisted candidate batch after a failed design review; never repeat generation or overwrite history.')
    parser.add_argument('--refresh-feasibility',action='store_true',help='Explicitly reassess current time/cost planning and request a new exact packet; old packets remain historical.')
    parser.add_argument('--max-actions',type=int,default=20,choices=range(1,21))
    parser.add_argument('--model-call-cap',type=int,default=40,choices=range(1,41))
    args=parser.parse_args()
    path=args.db or PROJECT_ROOT/create_demo()['db']
    print(f'FINAL DEMO LEDGER {path}',flush=True)
    try:
        result=asyncio.run(run(path,explicit_test_human=args.test_human,max_actions=args.max_actions,
            cap=args.model_call_cap,stop_at_approval=args.stop_at_approval,recover_design_review=args.recover_design_review,
            refresh_feasibility=args.refresh_feasibility))
    except Exception as error:
        print(public(f'FINAL_E2E_FAILED ({type(error).__name__}): {error}'),flush=True)
        return 1
    from autolab.final_demo_audit import audit
    with ResearchLedger(path) as ledger:
        complete=audit(ledger,require_complete=False)['status']=='PASS'
    print('AUTOLAB_FINAL_E2E_OK' if complete else 'AUTOLAB_FINAL_E2E_CHECKPOINT',flush=True)
    print(f'Report: {result["report"]}',flush=True)
    return 0 if complete or not args.test_human or args.stop_at_approval else 1

if __name__=='__main__':
    raise SystemExit(main())
