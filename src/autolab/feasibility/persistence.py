"""Read typed planning payloads from the existing append-only event history."""
import hashlib
import os
import re

from pydantic import ValidationError
from .models import ApprovalPacket, FeasibilityAssessment

HUMAN_ACTORS = {"human", "test-human"}
HUMAN_EVENTS = {"HUMAN_APPROVED", "HUMAN_REJECTED", "HUMAN_MODIFY", "HUMAN_MODIFICATION_REQUESTED"}


def spec_fingerprint(spec):
    return hashlib.sha256(spec.model_dump_json().encode()).hexdigest()


def assessment_fingerprint(assessment):
    return hashlib.sha256(assessment.model_dump_json().encode()).hexdigest()


def ensure_public(payload):
    """Reject credential values before saving or displaying planning inputs."""
    text = payload.model_dump_json() if hasattr(payload, "model_dump_json") else str(payload)
    credentials = [os.environ.get(name, "") for name in ("OPENAI_API_KEY", "HF_TOKEN", "HUGGINGFACE_HUB_TOKEN")]
    if (any(len(value) >= 8 and value in text for value in credentials)
        or re.search(r"sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16}", text)):
        raise ValueError("Credential values must not appear in feasibility or approval records.")


def selected_is_current(snapshot, experiment):
    return bool(experiment and not any(e.experiment_id == experiment.experiment_id and e.version > experiment.version
                                      for e in snapshot.experiments))


def current_assessment(snapshot, experiment=None):
    if experiment is None:
        from autolab.orchestration.state_machine import selected_experiment
        experiment = selected_experiment(snapshot)
    if not selected_is_current(snapshot, experiment):
        return None
    for event in reversed(snapshot.events):
        if event.actor != "feasibility" or event.event_type != "FEASIBILITY_ASSESSED" or event.target_id != experiment.experiment_id:
            continue
        try:
            assessment = FeasibilityAssessment.model_validate(event.payload.get("assessment"))
        except ValidationError:
            return None
        if assessment.experiment_version != experiment.version:
            continue
        if (assessment.project_id != snapshot.charter.project_id or event.project_id != assessment.project_id
            or assessment.experiment_id != experiment.experiment_id or assessment.spec_fingerprint != spec_fingerprint(experiment)):
            return None
        return assessment
    return None


def current_packet(snapshot, experiment=None):
    if experiment is None:
        from autolab.orchestration.state_machine import selected_experiment
        experiment = selected_experiment(snapshot)
    if not experiment:
        return None
    for event in reversed(snapshot.events):
        if event.actor != "approval" or event.event_type != "HUMAN_APPROVAL_REQUESTED" or event.target_id != experiment.experiment_id:
            continue
        try:
            packet = ApprovalPacket.model_validate(event.payload.get("packet"))
        except ValidationError:
            return None
        if packet.experiment_version != experiment.version:
            continue
        if (packet.project_id != snapshot.charter.project_id or event.project_id != packet.project_id
            or packet.experiment_id != experiment.experiment_id
            or packet.spec_fingerprint != spec_fingerprint(experiment)
            or packet.assessment_id != packet.assessment.assessment_id
            or packet.assessment_version != packet.assessment.version
            or packet.assessment.project_id != packet.project_id
            or packet.assessment.experiment_id != packet.experiment_id
            or packet.assessment.experiment_version != packet.experiment_version
            or packet.assessment.spec_fingerprint != packet.spec_fingerprint):
            return None
        return packet
    return None


def human_event(snapshot, experiment=None):
    if experiment is None:
        from autolab.orchestration.state_machine import selected_experiment
        experiment = selected_experiment(snapshot)
    return next((e for e in reversed(snapshot.events) if experiment and e.actor in HUMAN_ACTORS
                 and e.event_type in HUMAN_EVENTS and e.project_id == snapshot.charter.project_id
                 and e.payload.get("experiment_id") == experiment.experiment_id
                 and e.payload.get("experiment_version", 1) == experiment.version), None)


def packet_pending(snapshot):
    packet = current_packet(snapshot)
    if packet is None:
        return None
    response = human_event(snapshot)
    if response is None or response.payload.get("packet_id") != packet.packet_id or response.created_at < packet.created_at:
        return packet
    return None
