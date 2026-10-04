"""Offline selected contract → actual local configuration/unknowns → approval packet."""
from pathlib import Path
from tempfile import TemporaryDirectory
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.feasibility.approval import ApprovalService, render_packet
from autolab.feasibility.persistence import current_assessment, current_packet
from autolab.feasibility.service import FeasibilityService
from autolab.feasibility_smoke_helpers import save_report, seed_selected
from autolab.orchestration.snapshot import load_snapshot


def smoke():
    configure()
    with TemporaryDirectory(prefix="autolab-feasibility-") as directory:
        path=Path(directory)/"feasibility.db"
        with ResearchLedger(path) as ledger:
            project,experiment,provenance=seed_selected(ledger)
            assessment=FeasibilityService(ledger).assess(project.project_id,experiment.experiment_id)
            packet=ApprovalService(ledger).request_approval(project.project_id,experiment.experiment_id)
            assert ledger.get_experiment(experiment.experiment_id)==experiment
            assert all(c.actual_usd==0 and c.metadata["actual_known"] is False for c in ledger.list_costs(project.project_id))
            assert not any(e.event_type=="HUMAN_APPROVED" for e in ledger.list_events(project.project_id))
            output,snapshot=save_report("phase7-feasibility-smoke.json",ledger,project.project_id,
                assessment=assessment.model_dump(mode="json"),approval_packet=packet.model_dump(mode="json"),
                human_readable_packet=render_packet(packet),scientific_input=provenance)
        with ResearchLedger(path) as reopened:
            restored=load_snapshot(reopened,project.project_id)
            assert restored==snapshot and current_assessment(restored)==assessment and current_packet(restored)==packet
    print("AUTOLAB_FEASIBILITY_OK")
    print(render_packet(packet))
    print("Human approval required: yes")
    print("No resources prepared: yes; no experiment code generated: yes; no experiment executed: yes")
    print(f"Scientific output: {output}")


if __name__=="__main__":
    smoke()
