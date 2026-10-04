"""Explicit isolated test-human approval; optional one real PI decision, no dispatch."""
import argparse
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.feasibility.approval import ApprovalService, render_packet
from autolab.feasibility.persistence import current_assessment
from autolab.feasibility.service import FeasibilityService
from autolab.feasibility_smoke_helpers import explicit_test_planning, save_report, seed_selected
from autolab.orchestration.context_builder import ContextBuilder
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import approval_for
from autolab.planner import OmnigentPlanner
from autolab import schemas as s


def smoke(*,with_planner=False):
    configure()
    with TemporaryDirectory(prefix="autolab-approval-") as directory:
        path=Path(directory)/"approval.db"
        with ResearchLedger(path) as ledger:
            project,experiment,provenance=seed_selected(ledger)
            registry,inputs=explicit_test_planning(experiment)
            assessment=FeasibilityService(ledger,registry).assess(project.project_id,experiment.experiment_id,inputs)
            service=ApprovalService(ledger,allow_test_human=True)
            packet=service.request_approval(project.project_id,experiment.experiment_id)
            def prepare(snapshot):
                return s.NextDecision(decision_id="DEC_ELIGIBILITY",project_id=project.project_id,
                    action="PREPARE_RESOURCES",target_agent="preparation",reason="Eligibility check only; never dispatched",
                    remaining_budget_usd=project.budget_usd)
            before=load_snapshot(ledger,project.project_id)
            assert not DecisionValidator().validate(prepare(before),before).valid
            event=service.record_human_decision(project.project_id,experiment.experiment_id,experiment.version,"APPROVE",
                packet_id=packet.packet_id,actor="test-human",
                note="Explicit isolated test approval of stated test assumptions; preparation eligibility only")
            after=load_snapshot(ledger,project.project_id)
            assert DecisionValidator().validate(prepare(after),after).valid
            scope=approval_for(after,s.PlannerAction.PREPARE_RESOURCES)
            assert scope and scope.experiment_version==experiment.version and scope.assessment_id==assessment.assessment_id
            context=ContextBuilder().build(after)
            assert context.current_records["human_approval"]["scope_current"] is True
            route=None
            if with_planner:
                class OneCallPlanner(OmnigentPlanner):
                    async def propose(self,context,decision_id,feedback=None):
                        if self.calls:
                            raise RuntimeError("Optional smoke permits only one real Planner call; invalid output is reported.")
                        return await super().propose(context,decision_id,feedback)
                route=asyncio.run(Orchestrator(ledger,OneCallPlanner()).decide(project.project_id))
            assert ledger.get_experiment(experiment.experiment_id)==experiment
            output,snapshot=save_report("phase7-approval-smoke.json",ledger,project.project_id,
                assessment=assessment.model_dump(mode="json"),approval_packet=packet.model_dump(mode="json"),
                human_readable_packet=render_packet(packet),approval_event=event.model_dump(mode="json"),
                prepare_eligible_before=False,prepare_eligible_after=True,
                planner_route=route.model_dump(mode="json") if route else None,
                planner_context=context.model_dump(mode="json"),scientific_input=provenance,
                planning_configuration="Explicit isolated test declarations; not actual audited availability or provider prices")
        with ResearchLedger(path) as reopened:
            restored=load_snapshot(reopened,project.project_id)
            assert restored==snapshot and current_assessment(restored)==assessment
            assert approval_for(restored,s.PlannerAction.PREPARE_RESOURCES)==scope
            assert reopened.get(s.EventRecord,event.event_id)==event
    print("AUTOLAB_APPROVAL_OK")
    print(render_packet(packet))
    print(f"Experiment: {experiment.experiment_id}; approved version: {experiment.version}")
    print("Decision: APPROVE; actor: test-human; persisted: yes")
    print("PREPARE_RESOURCES eligible: yes; resources prepared: no")
    print("Experiment code generated: no; experiment executed: no")
    if route: print(f"Post-approval real Planner: {route.action.value} → {route.target_role}; returned route only")
    print(f"Scientific output: {output}")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-planner",action="store_true",help="Explicit optional one paid Planner call; no execution")
    smoke(with_planner=parser.parse_args().with_planner)
