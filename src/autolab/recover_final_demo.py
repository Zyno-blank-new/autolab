"""Explicit demo-only reconciliation through existing preparation/approval gates."""
import argparse,asyncio,json
from pathlib import Path
from autolab import schemas as s
from autolab.config import configure,PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.final_demo import PROJECT,require_demo,operator_catalog,recovery_facts
from autolab.final_e2e_integration_smoke import ObservedTransport,observed,request_packet
from autolab.preparation.agent import OmnigentPreparationAgent
from autolab.preparation.service import PreparationService
from autolab.preparation.recovery import propose_successor,activate_successor
from autolab.preparation.models import ResourcePreparationPlan
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_experiment
from autolab.feasibility.approval import render_packet
from autolab.event_stream import EventStream

async def recover(path,proposal=None):
 configure();path=require_demo(path);root=path.parent
 with ResearchLedger(path) as ledger:
  transport=ObservedTransport(root/'model_calls.json',cap=40)
  service=PreparationService(ledger,observed(OmnigentPreparationAgent(),transport),root=root)
  spec=selected_experiment(load_snapshot(ledger,PROJECT));service.catalog=operator_catalog(root,spec)
  stream=EventStream(PROJECT,root/'process.log')
  async def pump():
   while True:stream.refresh(ledger);await asyncio.sleep(.25)
  task=asyncio.create_task(pump())
  try:
   if proposal:
    result=activate_successor(service,PROJECT,proposal)
    # Reconcile the known failed preparation route only after the exact
    # successor has genuinely prepared resources. No readiness success inferred.
    snapshot=load_snapshot(ledger,PROJECT);decision=snapshot.decisions[-1]
    failed=any(e.event_type=='ADAPTIVE_SPECIALIST_FAILED' and e.payload.get('decision_id')==decision.decision_id for e in snapshot.events)
    if failed and decision.action==s.PlannerAction.PREPARE_RESOURCES:
     ledger.add_event(s.EventRecord(event_id=ledger.next_id('EVENT'),project_id=PROJECT,
      event_type='ADAPTIVE_CONTROL_RETURNED',actor='orchestrator',target_type='decisions',target_id=decision.decision_id,
      summary='Explicit preparation reconciliation: reapproved successor resources prepared; prior failure retained; independent readiness still required',
      payload={'decision_id':decision.decision_id,'successor_proposal_id':proposal,'manifest_id':result.manifest_id,'status':'PREPARED'}))
    print('SUCCESSOR_PREPARED '+result.manifest_id)
   else:
    event=await propose_successor(service,PROJECT,operator_evidence=recovery_facts(root,spec))
    plan=ResourcePreparationPlan.model_validate(event.payload['plan'])
    packet=request_packet(ledger,refresh=True,preparation_proposal=plan)
    print('SUCCESSOR_PROPOSAL '+event.event_id)
    print(render_packet(packet))
    print('EXPLICIT HUMAN REAPPROVAL REQUIRED; no successor activated or resource added.')
    (root/'successor_proposal.json').write_text(json.dumps({'event_id':event.event_id,'packet_id':packet.packet_id,'plan':plan.model_dump(mode='json'),'lineage':{k:v for k,v in event.payload.items() if k!='plan'}},indent=2)+'\n')
  finally:
   transport.flush(ledger);task.cancel()
   try:await task
   except asyncio.CancelledError:pass
   stream.refresh(ledger)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True)
 p.add_argument('--activate-successor',help='Actual persisted proposal ID; requires fresh exact human approval already recorded')
 a=p.parse_args();asyncio.run(recover(a.db,a.activate_successor))
if __name__=='__main__':main()
