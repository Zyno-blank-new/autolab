"""Plan -> constrained files -> deterministic tests -> independent bounded audit."""
import hashlib
import json
import re
from pathlib import Path
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.feasibility.persistence import ensure_public, spec_fingerprint
from autolab.orchestration.budget import calculate_budget
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_experiment, current_readiness, current_implementation
from autolab.planner.service import runtime_metadata
from autolab.preparation.manifest import current_manifest, fingerprint
from .agent import OmnigentImplementer, OmnigentCodeAuditor
from .contract import ExperimentRawOutput
from .harness import run_checks
from .models import ImplementationError, ImplementationPlan, SourceBundle, TestContract, ImplementationResult
from .persistence import implementation_pins, implementation_current, audited_implementation_passes, current_checks, review_pins
from .validation import validate_plan, source_hash, read_sources, required_requirements, ALLOWED_DEPENDENCIES, static_checks


class ImplementationService:
    def __init__(self, ledger, implementer=None, auditor=None, *, root=None, contracts=None, timeout_seconds=15):
        self.ledger = ledger
        self.implementer = implementer or OmnigentImplementer()
        self.auditor = auditor or OmnigentCodeAuditor()
        self.root = Path(root or PROJECT_ROOT).resolve()
        self.contracts = contracts or {}
        self.timeout_seconds = timeout_seconds

    def _event(self, project_id, kind, target=None, *, actor='implementation_validator', **payload):
        return s.EventRecord(event_id=self.ledger.next_id('EVENT'), project_id=project_id, event_type=kind,
            actor=actor, target_type='implementations' if target else None, target_id=target,
            summary=f'Phase 9 {kind}; no scientific execution', payload=payload)

    def _gate(self, snapshot, *, audit=False):
        decision = s.NextDecision(decision_id='DEC_IMPLEMENTATION_GATE', project_id=snapshot.charter.project_id,
            action='IMPLEMENT_EXPERIMENT', target_agent='code_auditor' if audit else 'implementer',
            reason='Exact Phase 9 gate check', remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd)
        result = DecisionValidator().validate(decision, snapshot)
        if not result.valid: raise ImplementationError('Implementation not authorized: ' + '; '.join(result.reasons))
        spec = selected_experiment(snapshot)
        contract = self.contracts.get(spec_fingerprint(spec))
        if not contract and audit:
            current = current_implementation(snapshot)
            if current: contract = current.metadata.get('test_contract')
        if not contract: raise ImplementationError('Independent framework test adapter missing for exact spec; escalate without redesign')
        contract = TestContract.model_validate(contract.model_dump() if isinstance(contract, TestContract) else contract)
        if contract.spec_fingerprint != spec_fingerprint(spec): raise ImplementationError('Stale framework test contract')
        return contract

    def _context(self, snapshot, contract, workspace):
        spec = selected_experiment(snapshot); manifest = current_manifest(snapshot)
        hypothesis = next((h for h in snapshot.hypotheses if h.hypothesis_id == spec.hypothesis_id and h.version == spec.hypothesis_version), None)
        summaries = []
        for pin in manifest.resources:
            data = json.loads(Path(pin.path).read_text())
            sample = data[0] if isinstance(data, list) and data else data
            summaries.append({'resource_id': pin.resource_id, 'kind': type(data).__name__,
                'count': len(data) if isinstance(data, (list, dict)) else None,
                'schema_sample': sample if len(json.dumps(sample)) < 5000 else 'Schema sample exceeds bound'})
        interfaces = {}
        for probe in contract.probes:
            if probe.raises or probe.component in interfaces: continue
            interfaces[probe.component] = {'positional_arguments': [type(a).__name__ for a in probe.args],
                'return_type': type(probe.expected).__name__,
                'return_fields': list(probe.expected) if isinstance(probe.expected, dict) else None}
        context = {'experiment_spec': spec.model_dump(mode='json'),
            'hypothesis': {'id': hypothesis.hypothesis_id, 'version': hypothesis.version, 'statement': hypothesis.statement} if hypothesis else None,
            'resource_manifest': manifest.model_dump(mode='json'), 'resource_summaries': summaries,
            'readiness_report': current_readiness(snapshot).model_dump(mode='json'),
            'workspace': str(workspace), 'requirement_fields': sorted(required_requirements(spec)),
            'base_experiment': {'class': 'Experiment(BaseExperiment)', 'methods': ['setup(self, context)', 'run(self, context)', 'collect_results(self, context)'],
                'import': 'from autolab.implementation.contract import BaseExperiment',
                'context': 'dict with experiment_id,experiment_version,seed,resources (resource_id to parsed JSON),resource_hashes (resource_id to sha256)'},
            'raw_output_schema': ExperimentRawOutput.model_json_schema(),
            'coding_conventions': 'Small Python files, explicit validation, no dependencies beyond approved stdlib, simple test_* functions',
            'allowed_dependencies': sorted(ALLOWED_DEPENDENCIES),
            'allowed_files': ['experiment.py', 'helpers.py', 'test_experiment.py'],
            'allowed_framework_imports': ['autolab.implementation.contract', 'experiment', 'helpers'],
            'execution_constraints': {'scientific_run': False, 'network': False, 'filesystem': 'No direct generated I/O; supplied context data only',
                'secrets': False, 'critical_placeholders': False, 'native_tools': False},
            'framework_adapter': {'metric_components': contract.metric_requirements,
                'required_components': contract.required_components, 'seeds': contract.expected_seeds,
                'setup_invariants': contract.expected_setup,
                'component_interfaces': interfaces,
                'framework_owned_probes': [p.model_dump(mode='json') for p in contract.probes],
                'failure_contract': 'Probe raises describe expected exception families, not exact subclass names. Failed-attempt accounting belongs to the approved spec and raw observation counts; the helper need not return a success dictionary on exception. An exception subclass with public count information is permitted if useful. This does not alter scientific conditions or budgets.',
                'invariant_descriptions': list(dict.fromkeys(p.requirement for p in contract.probes)), 'provenance': contract.provenance}}
        ensure_public(context)
        if len(json.dumps(context)) > 60000: raise ImplementationError('Context exceeds focused implementation limit')
        return context

    async def implement(self, project_id, *, previous=None, review=None):
        before = load_snapshot(self.ledger, project_id)
        contract = self._gate(before)
        latest = current_implementation(before)
        if previous is None and latest:
            raise ImplementationError('Implementation already exists; audit or bounded revise rather than restart the loop')
        if previous and (latest != previous or not review or review.verdict != s.ReviewVerdict.REVISE):
            raise ImplementationError('Revision requires latest exact implementation and REVISE review')
        revision = previous.metadata['revision'] + 1 if previous else 0
        if revision > 2: raise ImplementationError('Maximum two revisions exhausted')
        spec = selected_experiment(before); manifest = current_manifest(before); readiness = current_readiness(before)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', spec.experiment_id): raise ImplementationError('Unsafe experiment directory ID')
        identifier = self.ledger.next_id('IMPL')
        artifact = self.root/'experiments'/spec.experiment_id/'implementation'/identifier
        # The agent has no filesystem tools; only this trusted writer has write capability.
        if artifact.resolve() != artifact or not artifact.is_relative_to(self.root) or artifact.exists():
            raise ImplementationError('Experiment workspace is unconfined or already exists')
        context = self._context(before, contract, artifact/'source')
        assignment = {'project_id': project_id, 'experiment_id': spec.experiment_id, 'experiment_version': spec.version,
            'implementation_id': identifier, 'revision': revision, 'spec_fingerprint': spec_fingerprint(spec),
            'manifest_fingerprint': fingerprint(manifest), 'readiness_id': readiness.readiness_id}
        self.ledger.add_event(self._event(project_id, 'IMPLEMENTATION_STARTED', experiment_id=spec.experiment_id,
            experiment_version=spec.version, implementation_id=identifier, revision=revision))
        try:
            old_plan = ImplementationPlan.model_validate(previous.metadata['plan']) if previous else None
            proposed = await self.implementer.plan(context, assignment, previous=old_plan, review=review)
            plan = validate_plan(proposed, assignment, spec, manifest, contract, review.issues if review else ())
            ensure_public(plan)
            if plan.blockers:
                self.ledger.add_event(self._event(project_id, 'IMPLEMENTATION_BLOCKED', experiment_id=spec.experiment_id,
                    experiment_version=spec.version, blockers=plan.blockers, plan=plan.model_dump(mode='json')))
                raise ImplementationError('Faithful implementation blocked: ' + '; '.join(plan.blockers))
            def current_gate():
                fresh = load_snapshot(self.ledger, project_id)
                self._gate(fresh)
                if selected_experiment(fresh) != spec or current_manifest(fresh) != manifest or current_readiness(fresh) != readiness:
                    raise ImplementationError('Scientific dependencies changed during implementation')
            current_gate()
            self.ledger.add_many([self._event(project_id, 'IMPLEMENTATION_PLAN_CREATED', actor='implementer',
                implementation_id=identifier, plan=plan.model_dump(mode='json'), model_metadata=runtime_metadata(self.implementer))], check=current_gate)
            # Only create files after the exact plan is validated and persisted.
            artifact.mkdir(parents=True, exist_ok=False)
            source_dir = artifact/'source'; source_dir.mkdir()
            (artifact/'implementation_plan.json').write_text(plan.model_dump_json(indent=2))
            (artifact/'test_contract.json').write_text(contract.model_dump_json(indent=2))
            (artifact/'spec.json').write_text(spec.model_dump_json(indent=2))
            (artifact/'resource_manifest.json').write_text(manifest.model_dump_json(indent=2))
            (artifact/'readiness_report.json').write_text(readiness.model_dump_json(indent=2))
            generated = await self.implementer.generate(context, plan,
                previous_files=read_sources(previous) if previous else None, review=review)
            bundle = SourceBundle.model_validate(generated.model_dump() if isinstance(generated, SourceBundle) else generated)
            ensure_public(bundle)
            if set(bundle.files) != set(plan.expected_files) or any(len(v) > 40000 for v in bundle.files.values()):
                raise ImplementationError('Generated file paths or sizes violate constrained writer')
            for name, content in bundle.files.items():
                # Names were validated against the fixed flat allowlist in the plan.
                (source_dir/name).write_text(content)
            checks = await run_checks(bundle.files, plan, contract, source_dir, timeout_seconds=self.timeout_seconds)
            (artifact/'checks.json').write_text(checks.model_dump_json(indent=2))
            metadata = {'phase': 9, 'revision': revision, 'previous_implementation_id': previous.implementation_id if previous else None,
                'previous_code_hash': previous.code_version if previous else None, 'artifact_path': str(artifact),
                'plan': plan.model_dump(mode='json'), 'plan_fingerprint': fingerprint(plan),
                'test_contract': contract.model_dump(mode='json'), 'test_contract_fingerprint': fingerprint(contract),
                'checks': checks.model_dump(mode='json'), 'model_metadata': runtime_metadata(self.implementer),
                'file_hashes': {n: hashlib.sha256(v.encode()).hexdigest() for n,v in bundle.files.items()}}
            record = s.ImplementationRecord(implementation_id=identifier, project_id=project_id,
                experiment_id=spec.experiment_id, experiment_version=spec.version, code_path=str(source_dir),
                code_version=source_hash(bundle.files), status='AUDIT_PENDING', implementation_plan=plan.tests, metadata=metadata)
            pins = implementation_pins(before, record)
            record = record.model_copy(update={'metadata': {**metadata, 'pins': pins}})
            ensure_public(record)
            events = [self._event(project_id, 'IMPLEMENTATION_CREATED', identifier, actor='implementer', pins=pins,
                revision=revision, model_metadata=runtime_metadata(self.implementer)),
                self._event(project_id, 'IMPLEMENTATION_TESTED', identifier, pins=pins,
                    checks=checks.model_dump(mode='json'), checks_fingerprint=fingerprint(checks),
                    status='PASS' if checks.static_pass and checks.tests_pass else 'FAIL')]
            self.ledger.add_many([record, *events], check=current_gate)
            return record
        except Exception:
            self.ledger.add_event(self._event(project_id, 'IMPLEMENTATION_FAILED', implementation_id=identifier,
                experiment_id=spec.experiment_id, experiment_version=spec.version, reason='No new execution authorization; preserve previous artifacts/history'))
            raise

    async def audit(self, project_id):
        before = load_snapshot(self.ledger, project_id)
        contract = self._gate(before, audit=True)
        record = current_implementation(before)
        if not implementation_current(before, record): raise ImplementationError('Code or scientific provenance stale before audit')
        plan = ImplementationPlan.model_validate(record.metadata['plan'])
        files = read_sources(record); pins = review_pins(before, record)
        current_static = static_checks(files, plan, contract)
        assignment = {'review_id': self.ledger.next_id('HREV'), 'project_id': project_id, 'review_type': 'code',
            'target_type': 'implementations', 'target_id': record.implementation_id, 'target_version': 1,
            'reviewer_role': 'code_auditor', 'metadata': pins}
        started = self._event(project_id, 'CODE_AUDIT_STARTED', record.implementation_id, actor='code_auditor', pins=pins)
        self.ledger.add_event(started)
        baseline = load_snapshot(self.ledger, project_id)
        implementation_context = self._context(before, contract, Path(record.code_path))
        context = {'experiment_spec': selected_experiment(before).model_dump(mode='json'),
            'hypothesis': implementation_context['hypothesis'],
            'resource_manifest': current_manifest(before).model_dump(mode='json'),
            'readiness': {'id': pins['readiness_id'], 'verdict': 'PASS'}, 'implementation_plan': plan.model_dump(mode='json'),
            'files': files, 'deterministic_checks': current_checks(before, record).model_dump(mode='json') if current_checks(before, record) else {},
            'current_static_checks': current_static.model_dump(mode='json'),
            'base_experiment': 'setup(context),run(context),collect_results(context); no run in Phase 9',
            'raw_output_schema': ExperimentRawOutput.model_json_schema(),
            'framework_adapter': implementation_context['framework_adapter'],
            'limitations': ['Restricted offline Python worker is not an OS sandbox', 'Toy tests do not establish scientific outcomes']}
        ensure_public(context)
        try:
            proposed = await self.auditor.audit(context, assignment)
            review = s.ReviewRecord.model_validate(proposed.model_dump() if isinstance(proposed, s.ReviewRecord) else proposed)
            ensure_public(review)
            mismatches = [k for k,v in assignment.items() if getattr(review,k) != v]
            if mismatches:
                metadata_keys = [k for k,v in pins.items() if review.metadata.get(k) != v]
                self.ledger.add_event(self._event(project_id, 'CODE_REVIEW_BINDINGS_REJECTED', record.implementation_id,
                    actor='code_auditor', differing_fields=mismatches, differing_metadata_keys=metadata_keys,
                    extra_metadata_keys=sorted(set(review.metadata)-set(pins))))
                raise ImplementationError('Code review target/hash/dependency pins differ: ' + ','.join(mismatches)
                    + '; metadata keys: ' + ','.join(metadata_keys)
                    + '; extra metadata keys: ' + ','.join(set(review.metadata)-set(pins)))
            if len(review.model_dump_json()) > 50000: raise ImplementationError('Code audit exceeds bounded report')
            required = {'severity', 'component', 'requirement', 'problem', 'impact', 'correction'}
            if any(not required <= set(i) or any(not i[k] for k in required) for i in review.issues):
                raise ImplementationError('Review issues must be actionable')
            if review.verdict == 'PASS' and review.issues: raise ImplementationError('PASS cannot contain unresolved material issues')
            if review.verdict != 'PASS' and not review.issues: raise ImplementationError('Non-PASS needs specific material findings')
            checks = current_checks(before, record)
            accepted = review.verdict == 'PASS' and checks and checks.static_pass and checks.tests_pass and current_static.static_pass
            exhausted = review.verdict == 'REVISE' and record.metadata['revision'] >= 2
            events = [self._event(project_id, 'CODE_REVIEWED', record.implementation_id, actor='code_auditor',
                pins=pins, review_id=review.review_id, verdict=review.verdict.value, model_metadata=runtime_metadata(self.auditor))]
            if accepted:
                events.append(self._event(project_id, 'IMPLEMENTATION_APPROVED', record.implementation_id, pins=pins, review_id=review.review_id))
            elif review.verdict != 'REVISE' or exhausted:
                events.append(self._event(project_id, 'IMPLEMENTATION_BLOCKED', record.implementation_id, pins=pins,
                    review_id=review.review_id, reason='Revision limit exhausted' if exhausted else 'Independent audit or deterministic checks did not PASS'))
            def recheck():
                fresh = load_snapshot(self.ledger, project_id)
                if fresh != baseline or not implementation_current(fresh, record): raise ImplementationError('State/code changed during independent audit')
                self._gate(fresh, audit=True)
            self.ledger.add_many([review, *events], check=recheck)
            review_dir = Path(record.metadata['artifact_path'])/'reviews'; review_dir.mkdir(exist_ok=True)
            (review_dir/(review.review_id+'.json')).write_text(review.model_dump_json(indent=2))
            return review
        except Exception:
            self.ledger.add_event(self._event(project_id, 'CODE_AUDIT_FAILED', record.implementation_id, actor='code_auditor', pins=pins,
                reason='Malformed/failed independent audit; no new PASS authorization'))
            raise

    async def run(self, project_id, *, audit_only=False):
        record = current_implementation(load_snapshot(self.ledger, project_id)) if audit_only else await self.implement(project_id)
        reviews = []
        if audit_only:
            snapshot = load_snapshot(self.ledger, project_id)
            prior = next((r for r in reversed(snapshot.reviews) if r.review_type == 'code'
                and r.target_id == record.implementation_id and r.reviewer_role == 'code_auditor'), None)
            if (prior and prior.verdict == 'REVISE' and prior.metadata == review_pins(snapshot, record)
                and record.metadata['revision'] < 2):
                # Resume an interrupted justified revision without repeating the
                # same audit or discarding the immutable history/revision budget.
                reviews.append(prior.review_id)
                record = await self.implement(project_id, previous=record, review=prior)
        while True:
            review = await self.audit(project_id); reviews.append(review.review_id)
            snapshot = load_snapshot(self.ledger, project_id)
            if audited_implementation_passes(snapshot, record): status = 'READY'
            elif review.verdict != 'REVISE' or record.metadata['revision'] >= 2: status = 'BLOCK'
            else:
                record = await self.implement(project_id, previous=record, review=review)
                continue
            return ImplementationResult(implementation_id=record.implementation_id, status=status,
                revision_rounds=record.metadata['revision'], review_ids=reviews, code_hash=record.code_version)

    async def revalidate(self, project_id):
        before = load_snapshot(self.ledger, project_id)
        contract = self._gate(before, audit=True); record = current_implementation(before)
        if not implementation_current(before, record): raise ImplementationError('Stale code/provenance cannot be retested')
        report = await run_checks(read_sources(record), ImplementationPlan.model_validate(record.metadata['plan']),
            contract, record.code_path, timeout_seconds=self.timeout_seconds)
        event = self._event(project_id, 'IMPLEMENTATION_TESTED', record.implementation_id,
            pins=implementation_pins(before, record), checks=report.model_dump(mode='json'),
            checks_fingerprint=fingerprint(report), status='PASS' if report.static_pass and report.tests_pass else 'FAIL')
        root = Path(record.metadata['artifact_path'])/'validation'; root.mkdir(exist_ok=True)
        path = root/(event.event_id+'.json'); path.write_text(report.model_dump_json(indent=2))
        event = event.model_copy(update={'payload':{**event.payload,'report_path':str(path)}})
        def recheck():
            fresh = load_snapshot(self.ledger, project_id)
            if fresh != before or not implementation_current(fresh, record): raise ImplementationError('State changed during revalidation')
            self._gate(fresh, audit=True)
        self.ledger.add_many([event], check=recheck)
        return report
