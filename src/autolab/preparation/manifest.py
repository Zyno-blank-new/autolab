"""Exact immutable resource identities, event-backed contracts, integrity checks."""
import hashlib
import json
from pathlib import Path
from pydantic import ValidationError
from autolab import schemas as s
from autolab.feasibility.persistence import selected_is_current, spec_fingerprint
from autolab.orchestration.state_machine import selected_experiment
from .models import ResourceManifest, ResourcePreparationPlan


def fingerprint(record):
    return hashlib.sha256(json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def checksum(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(65536),b''): digest.update(chunk)
    return digest.hexdigest()


def repair_attempts(snapshot):
    """Rejected repair invocations consume the existing two-attempt bound."""
    exp=selected_experiment(snapshot)
    starts=[e for e in snapshot.events if exp and e.actor=='preparation'
        and e.event_type=='RESOURCE_PREPARATION_STARTED' and e.target_id==exp.experiment_id
        and e.payload.get('experiment_version')==exp.version and e.payload.get('repair_attempt',0)>0]
    plan=current_plan(snapshot)
    return max(len(starts),plan.version-1 if plan else 0)


def current_plan(snapshot):
    exp=selected_experiment(snapshot)
    if not selected_is_current(snapshot,exp): return None
    for event in reversed(snapshot.events):
        if event.event_type!='PREPARATION_PLAN_CREATED' or event.actor!='preparation': continue
        if event.target_id!=exp.experiment_id or event.payload.get('experiment_version')!=exp.version: continue
        try: plan=ResourcePreparationPlan.model_validate(event.payload['plan'])
        except (KeyError,ValidationError): return None
        return plan if (plan.project_id,plan.experiment_id,plan.experiment_version,plan.spec_fingerprint)==(exp.project_id,exp.experiment_id,exp.version,spec_fingerprint(exp)) else None
    return None


def current_manifest(snapshot):
    exp=selected_experiment(snapshot)
    if not selected_is_current(snapshot,exp): return None
    for event in reversed(snapshot.events):
        if event.event_type!='RESOURCE_MANIFEST_CREATED' or event.actor!='preparation': continue
        if event.target_id!=exp.experiment_id or event.payload.get('experiment_version')!=exp.version: continue
        try: manifest=ResourceManifest.model_validate(event.payload['manifest'])
        except (KeyError,ValidationError): return None
        plan=current_plan(snapshot)
        if (not plan or manifest.project_id!=exp.project_id or manifest.experiment_id!=exp.experiment_id
            or manifest.experiment_version!=exp.version or manifest.spec_fingerprint!=spec_fingerprint(exp)
            or manifest.plan_id!=plan.plan_id or manifest.plan_version!=plan.version): return None
        return manifest
    return None


def manifest_errors(snapshot, manifest, *, verify_files=True):
    errors=[]
    plan=current_plan(snapshot)
    if not plan: return ['Current preparation plan missing']
    requirements={r.requirement_id:r for r in plan.resource_requirements}
    if len(manifest.resources)!=len(requirements) or {p.requirement_id for p in manifest.resources}!=set(requirements):
        errors.append('Manifest does not cover every requirement exactly once')
    if len({p.resource_id for p in manifest.resources})!=len(manifest.resources): errors.append('Duplicate manifest resource IDs')
    if manifest.validation_requirements!={r.requirement_id:r.criteria for r in plan.resource_requirements}: errors.append('Manifest acceptance criteria differ from preregistered preparation contract')
    for pin in manifest.resources:
        record=next((r for r in snapshot.resources if r.resource_id==pin.resource_id),None)
        if (not record or record.project_id!=manifest.project_id or record.experiment_id!=manifest.experiment_id
            or record.experiment_version!=manifest.experiment_version or fingerprint(record)!=pin.record_fingerprint
            or record.path_or_uri!=pin.path or record.version!=pin.version or record.checksum!=pin.checksum
            or record.status!=pin.status):
            errors.append(f'{pin.resource_id}: resource pin does not resolve'); continue
        # A newly registered replacement invalidates the prior exact resource set.
        logical=record.metadata.get('logical_resource_id',record.resource_id)
        if any(r.metadata.get('logical_resource_id',r.resource_id)==logical and r.resource_id!=record.resource_id
            and r.created_at>record.created_at for r in snapshot.resources): errors.append(f'{record.resource_id}: superseded resource version')
        if verify_files:
            try:
                if not Path(pin.path).is_file() or checksum(pin.path)!=pin.checksum: errors.append(f'{pin.resource_id}: missing or changed artifact')
            except OSError: errors.append(f'{pin.resource_id}: unreadable artifact')
    if verify_files:
        try:
            if ResourceManifest.model_validate_json(Path(manifest.manifest_path).read_text())!=manifest:
                errors.append('Manifest file differs from persisted manifest')
        except (OSError,ValueError): errors.append('Manifest artifact is missing or malformed')
    return errors


def readiness_current(snapshot, report):
    manifest=current_manifest(snapshot)
    if not manifest or not report: return False
    if any(e.event_type in ('READINESS_AUDIT_STARTED','READINESS_AUDIT_FAILED')
        and e.actor=='readiness' and e.payload.get('experiment_id')==report.experiment_id
        and e.payload.get('experiment_version')==report.experiment_version and e.created_at>report.created_at
        for e in snapshot.events): return False
    if any(r.experiment_id==report.experiment_id and r.experiment_version==report.experiment_version
        and r.created_at>report.created_at for r in snapshot.resources): return False
    trusted=any(e.actor=='readiness'  and e.event_type=='READINESS_PASSED'
        and e.target_id==report.readiness_id and e.payload.get('manifest_id')==manifest.manifest_id
        for e in snapshot.events)
    if not trusted: return False
    pins=report.metadata.get('resource_pins')
    return bool(report.metadata.get('auditor_role')=='readiness' and report.metadata.get('manifest_id')==manifest.manifest_id
        and report.metadata.get('manifest_fingerprint')==fingerprint(manifest)
        and report.metadata.get('spec_fingerprint')==manifest.spec_fingerprint
        and pins==[p.model_dump(mode='json') for p in manifest.resources]
        and not manifest_errors(snapshot,manifest))
