"""Minimal explicit human interface: assess, show a packet, or record a decision."""
import argparse
import json
from pathlib import Path

from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.feasibility.approval import ApprovalService, render_packet
from autolab.feasibility.capability_registry import CapabilityRegistry
from autolab.feasibility.models import FeasibilityInputs
from autolab.feasibility.persistence import current_assessment, current_packet, ensure_public
from autolab.feasibility.service import FeasibilityService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="Existing research ledger; default configured ledger")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("assess", "show", "decide"):
        command = commands.add_parser(name)
        command.add_argument("--project", required=True)
        command.add_argument("--experiment", required=True)
        command.add_argument("--version", type=int, required=True)
        if name == "assess":
            command.add_argument("--config", type=Path, help="Public JSON with capabilities and assessment inputs; no secrets")
        if name == "decide":
            command.add_argument("--packet", required=True)
            command.add_argument("--decision", choices=["APPROVE", "MODIFY", "REJECT"])
            command.add_argument("--note")
            command.add_argument("--max-cost-usd", type=float)
            command.add_argument("--max-runtime-minutes", type=float)
            command.add_argument("--acknowledge-unknowns", action="store_true")
    args = parser.parse_args(argv)
    configure()
    with ResearchLedger(args.db) as ledger:
        service = ApprovalService(ledger)
        if args.command == "assess":
            config = json.loads(args.config.read_text()) if args.config else {}
            ensure_public(json.dumps(config))
            if set(config) - {"capabilities", "inputs"}:
                raise ValueError("Assessment configuration accepts only capabilities and inputs.")
            registry = CapabilityRegistry(config["capabilities"]) if "capabilities" in config else None
            FeasibilityService(ledger, registry).assess(args.project, args.experiment,
                FeasibilityInputs.model_validate(config.get("inputs", {})), experiment_version=args.version)
            packet = service.request_approval(args.project, args.experiment, experiment_version=args.version)
            print(render_packet(packet))
        else:
            packet = current_packet(load_snapshot(ledger, args.project))
            if not packet or (packet.experiment_id, packet.experiment_version) != (args.experiment, args.version):
                raise ValueError("No packet for this selected exact version; assess and request approval first.")
            if current_assessment(load_snapshot(ledger, args.project)) != packet.assessment:
                raise ValueError("Approval packet is stale; request a packet for the current assessment.")
            print(render_packet(packet))
            if args.command == "decide":
                # No default decision and no automatic approval. A supplied CLI
                # choice or typed human input is the only decision source.
                decision = args.decision or input("Type APPROVE, MODIFY or REJECT: ").strip().upper()
                event = service.record_human_decision(args.project, args.experiment, args.version, decision,
                    packet_id=args.packet, actor="human", note=args.note, max_cost_usd=args.max_cost_usd,
                    max_runtime_minutes=args.max_runtime_minutes, acknowledge_unknowns=args.acknowledge_unknowns)
                print(f"Persisted {event.event_type} for {args.experiment} v{args.version}. Control returns to Planner.")


if __name__ == "__main__":
    main()
