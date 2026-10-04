"""Executable eligibility requires current exact provenance, not a status string."""
from pathlib import Path
from autolab import schemas as s
from autolab.preparation.manifest import current_manifest, fingerprint
from autolab.feasibility.persistence import spec_fingerprint
from autolab.orchestration.state_machine import selected_experiment, current_readiness, readiness_passes
from .validation import read_sources


def implementation_pins(snapshot, implementation):
    spec = selected_experiment(snapshot); manifest = current_manifest(snapshot); readiness = current_readiness(snapshot)
    if not spec or not manifest or not readiness: return None
    return {'implementation_id': implementation.implementation_id, 'code_hash': implementation.code_version,
        'experiment_id': spec.experiment_id, 'experiment_version': spec.version,
        'spec_fingerprint': spec_fingerprint(spec), 'manifest_id': manifest.manifest_id,
        'manifest_fingerprint': fingerprint(manifest), 'resource_pins': [p.model_dump(mode='json') for p in manifest.resources],
        'readiness_id': readiness.readiness_id, 'readiness_fingerprint': fingerprint(readiness),
        'plan_fingerprint': implementation.metadata.get('plan_fingerprint'),
        'test_contract_fingerprint': implementation.metadata.get('test_contract_fingerprint')}


def implementation_current(snapshot, implementation):
    from .models import ImplementationPlan, TestContract, CheckReport
    try:
        pins = implementation_pins(snapshot, implementation)
        if not pins or not readiness_passes(snapshot) or implementation.metadata.get('pins') != pins: return False
        if implementation.status != 'AUDIT_PENDING': return False
        read_sources(implementation)
        plan = ImplementationPlan.model_validate(implementation.metadata['plan'])
        contract = TestContract.model_validate(implementation.metadata['test_contract'])
        if fingerprint(plan) != pins['plan_fingerprint'] or fingerprint(contract) != pins['test_contract_fingerprint']: return False
        root = Path(implementation.metadata['artifact_path'])
        if root.is_symlink() or root.resolve() != root: return False
        if ImplementationPlan.model_validate_json((root/'implementation_plan.json').read_text()) != plan: return False
        if TestContract.model_validate_json((root/'test_contract.json').read_text()) != contract: return False
        checks = CheckReport.model_validate(implementation.metadata['checks'])
        if CheckReport.model_validate_json((root/'checks.json').read_text()) != checks: return False
        return True
    except (OSError, ValueError, KeyError, RuntimeError): return False


def current_checks(snapshot, implementation):
    """Append-only retests supersede initial findings without rewriting history."""
    from .models import CheckReport
    pins = implementation_pins(snapshot, implementation)
    event = next((e for e in reversed(snapshot.events) if e.event_type == 'IMPLEMENTATION_TESTED'
        and e.actor == 'implementation_validator' and e.target_id == implementation.implementation_id), None)
    if not event or event.payload.get('pins') != pins: return None
    try:
        report = CheckReport.model_validate(event.payload['checks'])
        if event.payload.get('checks_fingerprint') != fingerprint(report): return None
        if event.payload.get('report_path'):
            path = Path(event.payload['report_path'])
            root = Path(implementation.metadata['artifact_path'])
            if path.resolve() != path or not path.is_relative_to(root) or not path.is_file(): return None
            if CheckReport.model_validate_json(path.read_text()) != report: return None
        return report
    except (KeyError, ValueError, OSError): return None


def review_pins(snapshot, implementation):
    pins = implementation_pins(snapshot, implementation)
    checks = current_checks(snapshot, implementation)
    return {**pins, 'checks_fingerprint': fingerprint(checks) if checks else None} if pins else None


def audited_implementation_passes(snapshot, implementation):
    if not implementation_current(snapshot, implementation): return False
    from .models import ImplementationPlan, TestContract
    from .validation import static_checks
    if not static_checks(read_sources(implementation), ImplementationPlan.model_validate(implementation.metadata['plan']),
        TestContract.model_validate(implementation.metadata['test_contract'])).static_pass: return False
    pins = review_pins(snapshot, implementation)
    review = next((r for r in reversed(snapshot.reviews) if r.review_type == 'code'
        and r.target_type in ('implementations', 'ImplementationRecord')
        and r.target_id == implementation.implementation_id and r.target_version == 1), None)
    if not review or review.reviewer_role != 'code_auditor' or review.verdict != s.ReviewVerdict.PASS or review.issues or review.metadata != pins:
        return False
    if any(e.actor == 'code_auditor' and e.event_type in ('CODE_AUDIT_STARTED', 'CODE_AUDIT_FAILED')
        and e.target_id == implementation.implementation_id and e.created_at > review.created_at for e in snapshot.events): return False
    checked = next((e for e in reversed(snapshot.events) if e.event_type == 'IMPLEMENTATION_TESTED'
        and e.actor == 'implementation_validator' and e.target_id == implementation.implementation_id), None)
    approved = next((e for e in reversed(snapshot.events) if e.event_type == 'IMPLEMENTATION_APPROVED'
        and e.actor == 'implementation_validator' and e.target_id == implementation.implementation_id), None)
    checks = current_checks(snapshot, implementation)
    return bool(checked and approved and checks and checked.payload.get('pins') == implementation_pins(snapshot, implementation)
        and checked.payload.get('checks_fingerprint') == fingerprint(checks)
        and approved.payload.get('pins') == pins and approved.payload.get('review_id') == review.review_id
        and checks.static_pass and checks.tests_pass and checks.test_count > 0 and checks.generated_count > 0)


def fingerprint_from_dict(value):
    from .models import CheckReport
    return fingerprint(CheckReport.model_validate(value))
