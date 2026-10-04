"""Explicit human decisions using the existing scoped HUMAN_* event mechanism."""
import textwrap
from autolab import schemas as s
from autolab.orchestration.budget import calculate_budget, calculate_time
from autolab.orchestration.models import ApprovalScope
from autolab.orchestration.snapshot import load_snapshot
from .models import ApprovalPacket, FeasibilityStatus as F, HumanDecision as D, HumanResponse
from .persistence import (assessment_fingerprint, current_assessment, current_packet, ensure_public,
                          spec_fingerprint)
from .service import FeasibilityError, require_selected


def requires_reassessment(snapshot, experiment, assessment):
    return any(e.event_type=='RESOURCE_PREPARATION_BLOCKED' and e.actor=='preparation'
        and e.target_id==experiment.experiment_id and e.payload.get('experiment_version')==experiment.version
        and e.payload.get('status')=='NEEDS_REAPPROVAL' and e.created_at>=assessment.created_at for e in snapshot.events)


class ApprovalService:
    def __init__(self, ledger, *, allow_test_human=False):
        self.ledger, self.allow_test_human = ledger, allow_test_human

    def request_approval(self, project_id, experiment_id, *, experiment_version=None):
        before = load_snapshot(self.ledger, project_id)
        require_human_decision_state(before)
        experiment = require_selected(before, experiment_id, experiment_version)
        assessment = current_assessment(before, experiment)
        if assessment is None:
            raise FeasibilityError("A current persisted feasibility assessment is required before an approval packet.")
        if requires_reassessment(before, experiment, assessment):
            raise FeasibilityError("Preparation discovered changed cost/risk; refresh feasibility with those findings before a new approval packet.")
        request = next((d for d in reversed(before.decisions) if d.action == s.PlannerAction.REQUEST_HUMAN_APPROVAL), None)
        selection = next((e for e in reversed(before.events) if e.event_type == "EXPERIMENT_SELECTED"
            and e.payload.get("experiment_id", e.target_id) == experiment_id
            and e.payload.get("version", 1) == experiment.version), None)
        packet = ApprovalPacket(packet_id=self.ledger.next_id("APKT"), project_id=project_id,
            experiment_id=experiment_id, experiment_version=experiment.version, assessment_id=assessment.assessment_id,
            assessment_version=assessment.version, spec_fingerprint=spec_fingerprint(experiment), title=experiment.title,
            hypothesis_id=experiment.hypothesis_id, hypothesis_version=experiment.hypothesis_version,
            objective=experiment.objective, primary_metric=experiment.primary_metric,
            selection_reason=selection.payload.get("reason", selection.summary) if selection else "No selection reason recorded.",
            expected_information_gain=experiment.expected_information_gain, assessment=assessment,
            remaining_budget_usd=calculate_budget(before).remaining_budget_usd,
            remaining_time_minutes=calculate_time(before).remaining_minutes,
            decision_id=request.decision_id if request else None)
        ensure_public(packet)
        event = s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id,
            event_type="HUMAN_APPROVAL_REQUESTED", actor="approval", target_type="experiments", target_id=experiment_id,
            summary=f"Human decision requested for {experiment_id} v{experiment.version}: {assessment.status.value}",
            payload={"packet": packet.model_dump(mode="json")})
        def recheck():
            if load_snapshot(self.ledger, project_id) != before:
                raise FeasibilityError("State changed while building the approval packet; request a current packet.")
        self.ledger.add_many([event], check=recheck)
        return packet

    def record_human_decision(self, project_id, experiment_id, experiment_version, decision, *,
                              packet_id, actor="human", note=None, max_cost_usd=None,
                              max_runtime_minutes=None, acknowledge_unknowns=False, approved_actions=None):
        before = load_snapshot(self.ledger, project_id)
        require_human_decision_state(before)
        experiment = require_selected(before, experiment_id, experiment_version)
        packet = current_packet(before, experiment)
        assessment = current_assessment(before, experiment)
        if (not packet or packet.packet_id != packet_id or not assessment or packet.assessment != assessment
            or packet.spec_fingerprint != spec_fingerprint(experiment)):
            raise FeasibilityError("Approval packet or assessment is missing/stale; review a current packet.")
        response = HumanResponse(project_id=project_id, experiment_id=experiment_id, experiment_version=experiment_version,
            packet_id=packet_id, assessment_id=assessment.assessment_id, assessment_version=assessment.version,
            actor=actor, decision=decision, note=note)
        ensure_public(response)
        if actor == "test-human" and not self.allow_test_human:
            raise FeasibilityError("Test-human decisions are allowed only in explicitly configured test/smoke services.")
        if response.decision == D.APPROVE:
            if requires_reassessment(before, experiment, assessment):
                raise FeasibilityError("Changed preparation cost/risk requires refreshed feasibility and a new human packet.")
            if assessment.status in (F.BLOCKED, F.NEEDS_USER_INPUT) or assessment.blockers or assessment.user_input_required:
                raise FeasibilityError("Blockers and required user inputs must be resolved before APPROVE.")
            if assessment.has_unknown_estimates and not acknowledge_unknowns:
                raise FeasibilityError("Explicitly acknowledge unknown estimates and supply spending/runtime caps before APPROVE.")
            # Known ranges propose bounds; unknowns require explicit human caps.
            cost = max_cost_usd if max_cost_usd is not None else assessment.cost.estimate_usd.maximum
            duration = max_runtime_minutes if max_runtime_minutes is not None else assessment.runtime_minutes.maximum
            if cost is None or duration is None:
                raise FeasibilityError("Explicit maximum cost and pursuit duration are required for unknown estimates.")
            # Explicit human-supplied action scope; default remains preparation only.
            actions = [s.PlannerAction(a) for a in (approved_actions if approved_actions is not None else [s.PlannerAction.PREPARE_RESOURCES])]
            if not actions or len(actions) != len(set(actions)) or not set(actions) <= {s.PlannerAction.PREPARE_RESOURCES, s.PlannerAction.IMPLEMENT_EXPERIMENT}:
                raise FeasibilityError("This approval interface accepts preparation and explicit implementation eligibility only; no run approval.")
            scope = ApprovalScope(experiment_id=experiment_id, experiment_version=experiment_version,
                approved_actions=actions, max_cost_usd=cost, max_runtime_minutes=duration,
                assessment_id=assessment.assessment_id, assessment_version=assessment.version,
                assessment_fingerprint=assessment_fingerprint(assessment), spec_fingerprint=spec_fingerprint(experiment),
                packet_id=packet_id, note=note, acknowledged_unknowns=acknowledge_unknowns, decision_id=packet.decision_id)
            remaining = calculate_budget(before).remaining_budget_usd
            time = calculate_time(before).remaining_minutes
            if scope.max_cost_usd > remaining or (time is not None and scope.max_runtime_minutes > time):
                raise FeasibilityError("Human scope cannot exceed the remaining charter budget/time.")
            if (assessment.cost.estimate_usd.maximum is not None and assessment.cost.estimate_usd.maximum > scope.max_cost_usd
                or assessment.runtime_minutes.maximum is not None and assessment.runtime_minutes.maximum > scope.max_runtime_minutes):
                raise FeasibilityError("Known estimate upper bounds exceed the proposed approval scope.")
            payload = scope.model_dump(mode="json")
        else:
            payload = response.model_dump(mode="json")
            payload["decision_id"] = packet.decision_id
        kind = {D.APPROVE: "HUMAN_APPROVED", D.MODIFY: "HUMAN_MODIFICATION_REQUESTED", D.REJECT: "HUMAN_REJECTED"}[response.decision]
        event = s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id, event_type=kind,
            actor=actor, target_type="experiments", target_id=experiment_id,
            summary=f"Explicit {actor} decision {response.decision.value} for {experiment_id} v{experiment_version}", payload=payload)
        def recheck():
            if load_snapshot(self.ledger, project_id) != before:
                raise FeasibilityError("State changed before human decision persistence; review a current packet.")
        self.ledger.add_many([event], check=recheck)
        return event


def require_human_decision_state(snapshot):
    from autolab.orchestration.state_machine import derive_control_state
    from autolab.orchestration.models import ControlStage as C
    state = derive_control_state(snapshot)
    if state in (C.PAUSED, C.COMPLETED, C.RUNNING):
        raise FeasibilityError(f'Human decision cannot be recorded while project is {state.value}; '
                               'resume a paused project first. A terminal stop cannot be resumed.')


def format_range(value, *, currency=False):
    def number(x):
        return ("$" if currency else "") + format(x, ".6g")
    if value.minimum is not None and value.maximum is not None:
        return f"{number(value.minimum)}–{number(value.maximum)} (estimate)"
    if value.expected is not None:
        return f"Expected {number(value.expected)}; bounds UNKNOWN"
    return "UNKNOWN"


def render_packet(packet):
    assessment = packet.assessment
    rows = [f"Proceed with {packet.experiment_id} v{packet.experiment_version}?", packet.title,
        f"Hypothesis: {packet.hypothesis_id} v{packet.hypothesis_version}", f"Objective: {packet.objective}",
        f"Primary metric: {packet.primary_metric}",
        f"Why this experiment: {packet.selection_reason[:600]}{'…' if len(packet.selection_reason) > 600 else ''}",
        f"Expected information gain (advisory): {packet.expected_information_gain}",
        f"Feasibility: {assessment.status.value}",
        f"Estimated cost: {format_range(assessment.cost.estimate_usd, currency=True)}",
        f"Remaining project budget: ${packet.remaining_budget_usd:g}; {assessment.budget_status.value}",
        f"Estimated total pursuit time: {format_range(assessment.runtime_minutes)} minutes",
        f"Remaining project time: {round(packet.remaining_time_minutes, 1) if packet.remaining_time_minutes is not None else 'no configured limit'} minutes; {assessment.time_status.value}",
        f"Implementation complexity (advisory): {assessment.implementation_complexity.value}",
        f"Storage requirement: {format_range(assessment.storage_gb) if assessment.storage_gb else 'UNKNOWN'} GB"]
    groups = [("Resources required (not prepared)", assessment.required_resources),
        ("Capabilities", [f"{c.capability_id}: {c.status.value}" for c in assessment.capabilities]),
        ("Credential names (never values)", assessment.credential_requirements),
        ("Compute requirements", assessment.compute_requirements),
        ("External APIs", assessment.external_api_requirements),
        ("Unresolved resource access", assessment.unresolved_resource_requirements),
        ("Cost assumptions", assessment.cost.assumptions), ("Unknown cost drivers", assessment.cost.unknown_cost_drivers),
        ("Runtime assumptions", assessment.runtime_assumptions), ("Unknown runtime drivers", assessment.unknown_runtime_drivers),
        ("Blockers", assessment.blockers), ("Warnings", assessment.warnings),
        ("User input required", assessment.user_input_required), ("Execution risks", assessment.execution_risks)]
    for label, values in groups:
        rows.append(label + ":" + ("" if values else " none"))
        rows.extend("  - " + value for value in values)
    rows += ["Options: APPROVE / MODIFY / REJECT", "APPROVE permits pursuing this exact version within human cost/time caps; it is not scientific proof or readiness certification.",
             "No resources, implementation or experiment execution occurs here.", f"Packet: {packet.packet_id}"]
    return "\n".join(textwrap.fill(row, width=100, subsequent_indent="    ") for row in rows)
