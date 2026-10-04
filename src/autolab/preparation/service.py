"""Exact-approved resource preparation with append-only history and bounded repair."""
import json
import os
import re
from pathlib import Path
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.feasibility.capability_registry import CapabilityRegistry
from autolab.feasibility.persistence import ensure_public, current_assessment, spec_fingerprint
from autolab.orchestration.budget import calculate_budget
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import approval_for, selected_experiment
from autolab.planner.service import runtime_metadata
from .agent import OmnigentPreparationAgent
from .handlers import default_handlers
from .handlers.base import MAX_BYTES, require_keys
from .manifest import checksum, current_plan, current_manifest, fingerprint, repair_attempts
from .models import PreparationError, PreparationResult, ResourcePin, ResourceManifest, ResourcePreparationPlan


class PreparationService:
    def __init__(self, ledger, agent=None, *, registry=None, root=None, allowed_roots=(), allowed_downloads=(), handlers=None, catalog=()):
        self.ledger=ledger; self.agent=agent or OmnigentPreparationAgent()
        self.root=Path(root or PROJECT_ROOT).resolve()
        self.registry=registry or CapabilityRegistry.local(self.root)
        self.allowed_roots=(self.root,*map(Path,allowed_roots))
        self.allowed_downloads=set(allowed_downloads)
        self.handlers=default_handlers() if handlers is None else handlers
        self.catalog=list(catalog)

    def _public(self, payload, *, names=()):
        ensure_public(payload)
        encoded=payload.model_dump_json() if hasattr(payload,'model_dump_json') else str(payload)
        configured={c.credential_requirement for c in self.registry.capabilities.values() if c.credential_requirement}|set(names)
        if any(len(os.environ.get(n,''))>=8 and os.environ[n] in encoded for n in configured):
            raise PreparationError('Credential values cannot appear in preparation artifacts')

    def _event(self, project, kind, experiment, summary, **payload):
        return s.EventRecord(event_id=self.ledger.next_id('EVENT'),project_id=project,event_type=kind,
            actor='preparation',target_type='experiments',target_id=experiment.experiment_id,summary=summary,
            payload={'experiment_version':experiment.version,**payload})

    def _gate(self, snapshot, *, readiness=False):
        action=s.NextDecision(decision_id='DEC_PREPARATION_GATE',project_id=snapshot.charter.project_id,
            action='PREPARE_RESOURCES',target_agent='readiness' if readiness else 'preparation',reason='Exact approved preparation gate',
            remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd)
        validation=DecisionValidator().validate(action,snapshot)
        if not validation.valid: raise PreparationError('Preparation is not authorized: '+'; '.join(validation.reasons))
        return selected_experiment(snapshot)

    def _result(self, experiment, status, summary, **kwargs):
        return PreparationResult(project_id=experiment.project_id,experiment_id=experiment.experiment_id,
            experiment_version=experiment.version,status=status,summary=summary,**kwargs)

    def _validate_plan(self, plan, assignment, experiment, previous, issues, *, plan_omission=False):
        plan=ResourcePreparationPlan.model_validate(plan.model_dump() if isinstance(plan,ResourcePreparationPlan) else plan)
        ensure_public(plan)
        names={r.credential_requirement for r in plan.resource_requirements if r.credential_requirement}
        names.update(c.credential_requirement for c in self.registry.capabilities.values() if c.credential_requirement)
        if any(len(os.environ.get(n,''))>=8 and os.environ[n] in plan.model_dump_json() for n in names):
            raise PreparationError('Credential values cannot appear in preparation records')
        for key,value in assignment.items():
            if getattr(plan,key)!=value: raise PreparationError('Plan changed an assigned ID/version or scientific fingerprint')
        required=set(experiment.required_resources)
        mapped={r for resource in plan.resource_requirements for r in resource.spec_requirements}
        if mapped-required: raise PreparationError('Plan introduced an unregistered scientific requirement')
        if required-mapped and not (plan.blockers or plan.user_input_required or plan.material_changes):
            raise PreparationError('Plan omitted required ExperimentSpec resources')
        modes={'local':{'EXISTING','USER_PROVIDED'},'synthetic':{'GENERATE','SYNTHESIZE'},
            'transform':{'TRANSFORM','DERIVE'},'download':{'DOWNLOAD'}}
        seen=set()
        for requirement in plan.resource_requirements:
            if requirement.acquisition_mode not in modes[requirement.handler] or not set(requirement.dependencies)<=seen:
                raise PreparationError('Unsupported handler mode, cyclic or missing dependency')
            seen.add(requirement.requirement_id)
            contracts={'local':({'path'},{'path'}),
                'synthetic':({'data','seed','shuffle','specification','license'},{'data','specification'}),
                'download':({'url','sha256','license'},{'url','sha256'}),
                'transform':({'parent_requirement','operation','fields','seed','group_field','split_field','train_fraction'},{'parent_requirement','operation'})}
            allowed, needed=contracts[requirement.handler]
            require_keys(requirement.parameters,allowed,() if plan.blockers or plan.user_input_required or plan.material_changes else needed)
            encoded=json.dumps(requirement.parameters,allow_nan=False)
            if len(encoded.encode())>MAX_BYTES: raise PreparationError('Resource input exceeds bound')
        if previous:
            old={r.requirement_id:r for r in previous.resource_requirements}
            proposed_ids={r.requirement_id for r in plan.resource_requirements}
            if (not plan_omission and set(old)!=proposed_ids) or (plan_omission and not set(old)<proposed_ids):
                raise PreparationError('Repair cannot change required resource set')
            if plan_omission:
                from .recovery import validate_omissions
                validate_omissions(plan,previous,experiment)
            old_manifest=next((ResourceManifest.model_validate(e.payload['manifest']) for e in reversed(self.ledger.list_events(experiment.project_id))
                if e.event_type=='RESOURCE_MANIFEST_CREATED' and e.payload.get('manifest',{}).get('plan_id')==previous.plan_id
                and e.payload['manifest'].get('plan_version')==previous.version), None)
            pins={p.resource_id:p.requirement_id for p in old_manifest.resources} if old_manifest else {}
            accepted_indices={r.issue_index for r in plan.issue_responses if r.disposition=='ACCEPT'}
            accepted_requirements={pins[i] for n,issue in enumerate(issues) if n in accepted_indices
                for i in issue.get('resource_ids',[]) if i in pins}
            # A manifest-wide issue explicitly applies to the full set.
            if any(n in accepted_indices and not issue.get('resource_ids') for n,issue in enumerate(issues)):
                accepted_requirements=set(old)
            for r in plan.resource_requirements:
                if r.requirement_id not in old:
                    continue  # Independently checked, explicitly reapproved Class B addition.
                original=old[r.requirement_id]
                if r.requirement_id not in accepted_requirements and r!=original:
                    raise PreparationError('Repair may change only resources covered by an ACCEPT issue')
                if (r.criteria!=original.criteria or r.spec_requirements!=original.spec_requirements
                    or r.purpose!=original.purpose or r.resource_type!=original.resource_type):
                    raise PreparationError('Repair cannot relax acceptance or redesign science')
            if sorted(r.issue_index for r in plan.issue_responses)!=list(range(len(issues))):
                raise PreparationError('Repair requires exactly one response to each auditor issue')
        return plan

    def _constraints(self, snapshot, plan):
        scope=approval_for(snapshot,s.PlannerAction.PREPARE_RESOURCES)
        assessment=current_assessment(snapshot)
        if not scope or not assessment: return 'NEEDS_REAPPROVAL', ['Current exact human scope is missing']
        status='BLOCK' if plan.blockers or plan.material_changes else 'NEEDS_USER_INPUT' if plan.user_input_required else None
        reasons=plan.blockers+plan.material_changes+plan.user_input_required
        costs=[r.estimated_cost_usd for r in plan.resource_requirements]
        runtimes=[r.estimated_runtime_minutes for r in plan.resource_requirements]
        if not plan.blockers and not plan.material_changes and (set(plan.additional_risks)-set(assessment.execution_risks) or any(c is not None and c>scope.max_cost_usd for c in costs)
            or sum(c or 0 for c in costs)>scope.max_cost_usd or sum(t or 0 for t in runtimes)>scope.max_runtime_minutes
            or any(c is None for c in costs) and not scope.acknowledged_unknowns
            or any(t is None for t in runtimes) and not scope.acknowledged_unknowns):
            status='NEEDS_REAPPROVAL'; reasons+=plan.additional_risks+['Preparation changes approved risk/cost/time assumptions; current human scope cannot cover it']
        caps=self.registry.check([c for r in plan.resource_requirements for c in r.required_capabilities])
        for cap in caps:
            if cap.cost_driver and cap.capability_id not in assessment.required_capabilities:
                if status!='BLOCK': status='NEEDS_REAPPROVAL'
                reasons.append(f'{cap.capability_id}: new paid capability outside assessed scope')
            if cap.status=='UNAVAILABLE': status='BLOCK'; reasons.append(f'{cap.capability_id}: unavailable')
            elif cap.status!='AVAILABLE':
                if status!='BLOCK': status='NEEDS_USER_INPUT'
                reasons.append(f'{cap.capability_id}: {cap.status.value}; configure {cap.credential_requirement or cap.configuration_requirement or "capability"}')
            elif cap.credential_requirement and not os.environ.get(cap.credential_requirement,'').strip():
                if status!='BLOCK': status='NEEDS_USER_INPUT'
                reasons.append(f'Configure credential environment variable {cap.credential_requirement}')
        for r in plan.resource_requirements:
            if r.credential_requirement and not os.environ.get(r.credential_requirement,'').strip():
                if status!='BLOCK': status='NEEDS_USER_INPUT'
                reasons.append(f'Configure credential environment variable {r.credential_requirement}')
        return status, reasons

    async def prepare(self, project_id, *, issues=None, previous=None):
        before=load_snapshot(self.ledger,project_id)
        experiment=self._gate(before)
        prior=current_plan(before)
        if prior and previous is None:
            manifest=current_manifest(before)
            if manifest:
                return self._result(experiment,'PREPARED','Existing manifest returned without duplicate preparation',plan_id=prior.plan_id,
                    manifest_id=manifest.manifest_id,resource_ids=[p.resource_id for p in manifest.resources],repair_attempts=repair_attempts(before))
            status,reasons=self._constraints(before,prior)
            if status:
                return self._result(experiment,status,'; '.join(reasons),plan_id=prior.plan_id,
                    repair_attempts=repair_attempts(before),warnings=prior.warnings)
            return self._create(prior,experiment,None,[])
        if previous and (previous!=prior or previous.version>=3 or repair_attempts(before)>=2): raise PreparationError('Repair limit exceeded or prior plan stale')
        if previous:
            report=next((r for r in reversed(before.readiness) if r.experiment_id==experiment.experiment_id and r.experiment_version==experiment.version),None)
            expected_issues=report.metadata.get('issues') if report else None
            if (not report or report.verdict!='REPAIR' or report.metadata.get('manifest_id')!=current_manifest(before).manifest_id
                or issues!=expected_issues):
                raise PreparationError('Repair must respond to the persisted current independent REPAIR report')
        version=previous.version+1 if previous else 1
        assignment={'plan_id':previous.plan_id if previous else self.ledger.next_id('PPLAN'),
            'version':version,'project_id':project_id,'experiment_id':experiment.experiment_id,
            'experiment_version':experiment.version,'spec_fingerprint':spec_fingerprint(experiment)}
        self.ledger.add_event(self._event(project_id,'RESOURCE_PREPARATION_STARTED',experiment,'Approved resource preparation started',repair_attempt=repair_attempts(before)+1 if previous else 0))
        snapshot=load_snapshot(self.ledger,project_id)
        scope=approval_for(snapshot,s.PlannerAction.PREPARE_RESOURCES)
        assessment=current_assessment(snapshot)
        context={'experiment_spec':experiment.model_dump(mode='json'),
            'feasibility':assessment.model_dump(mode='json'),'approval':scope.model_dump(mode='json'),
            'remaining_budget_usd':calculate_budget(snapshot).remaining_budget_usd,
            'capabilities':[{**c.model_dump(mode='json'), 'provider': 'local executable (path withheld)' if c.provider and c.provider.startswith('/') else c.provider} for c in self.registry.capabilities.values()],
            'resource_catalog':self.catalog,'allowed_downloads':sorted(self.allowed_downloads),
            'artifact_storage':{'generated_outputs':'Service assigns immutable experiment-scoped JSON paths; agent must not choose paths',
                'access':'Input, hidden-reference and fault/config artifacts remain separate logical resources; future implementer must enforce visibility in its code',
                'downloads':'Only operator allowlist','existing':'Only operator catalog paths'}}
        ensure_public(context)
        try:
            proposed=await self.agent.plan(context,assignment,previous=previous,issues=issues)
            plan=self._validate_plan(proposed,assignment,experiment,previous,issues or [])
            fresh=load_snapshot(self.ledger,project_id)
            if fresh!=snapshot: raise PreparationError('State changed during preparation planning')
            self._gate(fresh)
            self.ledger.add_event(self._event(project_id,'PREPARATION_PLAN_CREATED',experiment,'Acceptance contract recorded before resource creation',
                plan=plan.model_dump(mode='json'),model_metadata=runtime_metadata(self.agent)))
            status,reasons=self._constraints(load_snapshot(self.ledger,project_id),plan)
            if status:
                self.ledger.add_event(self._event(project_id,'RESOURCE_PREPARATION_BLOCKED',experiment,'Preparation stopped before any resource action',status=status,reasons=reasons))
                return self._result(experiment,status,'; '.join(reasons),plan_id=plan.plan_id,repair_attempts=repair_attempts(load_snapshot(self.ledger,project_id)),warnings=plan.warnings)
            return self._create(plan,experiment,previous,issues or [])
        except Exception:
            self.ledger.add_event(self._event(project_id,'RESOURCE_PREPARATION_FAILED',experiment,'Resource preparation failed; prior immutable records retained'))
            # Never echo untrusted provider or handler exception text (could include secrets).
            raise PreparationError('Preparation failed; inspect validated plan and gates, prior ledger remains intact') from None

    def _create(self, plan, experiment, previous, issues, *, responses=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',experiment.experiment_id):
            raise PreparationError('Experiment ID cannot be used as a safe artifact directory')
        snapshot=load_snapshot(self.ledger,experiment.project_id)
        if self._gate(snapshot)!=experiment or current_plan(snapshot)!=plan:
            raise PreparationError('Creation requires the current persisted exact-spec preparation contract')
        status,reasons=self._constraints(snapshot,plan)
        if status: raise PreparationError('Resource action blocked: '+'; '.join(reasons))
        # current_manifest is intentionally stale after the new plan event; use the last immutable snapshot for repair parents.
        prior_pins={}
        if previous:
            for e in reversed(snapshot.events):
                if e.event_type=='RESOURCE_MANIFEST_CREATED' and e.payload.get('manifest',{}).get('plan_version')==previous.version:
                    old=ResourceManifest.model_validate(e.payload['manifest'])
                    if old.plan_id==plan.plan_id: prior_pins={p.requirement_id:p for p in old.resources}; break
        resources={}; records=[]; events=[]; written=[]
        if not re.fullmatch(r'[A-Za-z0-9_-]+',experiment.experiment_id):
            raise PreparationError('Experiment ID cannot be used as a safe artifact directory')
        base=self.root/'experiments'/experiment.experiment_id/f'v{experiment.version}'/'resources'
        if not base.resolve().is_relative_to(self.root): raise PreparationError('Artifact directory escapes configured root')
        try:
            base.mkdir(parents=True,exist_ok=True)
            for requirement in plan.resource_requirements:
                fresh=load_snapshot(self.ledger,experiment.project_id)
                self._gate(fresh)
                if self._constraints(fresh,plan)[0]: raise PreparationError('Capability or approval scope changed before resource action')
                previous_pin=prior_pins.get(requirement.requirement_id)
                original=next((r for r in snapshot.resources if previous_pin and r.resource_id==previous_pin.resource_id),None)
                accepted={response.issue_index for response in (plan.issue_responses if responses is None else responses) if response.disposition=='ACCEPT'}
                recreate=not original or any(n in accepted and (not issue.get('resource_ids') or original.resource_id in issue['resource_ids'])
                    for n,issue in enumerate(issues))
                if not recreate:
                    if not Path(original.path_or_uri).is_file() or checksum(original.path_or_uri)!=original.checksum:
                        raise PreparationError('Unchanged resource has lost integrity; explicit ACCEPT repair required')
                    resources[requirement.requirement_id]=original
                    continue
                artifact=self.handlers[requirement.handler].prepare(requirement,{'allowed_roots':self.allowed_roots,
                    'allowed_downloads':self.allowed_downloads,
                    'allowed_local_paths':{str(Path(c['path']).resolve()) for c in self.catalog if isinstance(c,dict) and c.get('path')},
                    'resources':resources})
                identifier=self.ledger.next_id('RES')
                if artifact.existing_path:
                    # Import once into a content-addressed shared cache. Subsequent
                    # experiments reference the same bytes, never copy per experiment.
                    original_path=artifact.existing_path
                    content=original_path.read_bytes()
                    self._public(content.decode('utf-8'),names=[requirement.credential_requirement] if requirement.credential_requirement else [])
                    digest=checksum(original_path)
                    shared=self.root/'data'/'shared'
                    if not shared.resolve().is_relative_to(self.root): raise PreparationError('Shared cache escapes configured root')
                    shared.mkdir(parents=True,exist_ok=True)
                    path=shared/(digest+original_path.suffix.lower())
                    if path.exists():
                        if checksum(path)!=digest: raise PreparationError('Immutable shared cache integrity failure')
                    else:
                        with path.open('xb') as f: f.write(content)
                        written.append(path)
                    artifact.metadata.update({'source_path':str(original_path),'source_checksum':digest,
                        'acquisition':'Imported once into content-addressed shared cache; never copied per experiment'})
                else:
                    if artifact.content is None or len(artifact.content)>MAX_BYTES: raise PreparationError('Invalid handler artifact')
                    self._public(artifact.content.decode('utf-8'),names=[requirement.credential_requirement] if requirement.credential_requirement else [])
                    path=base/(identifier+'.json')
                    with path.open('xb') as file: file.write(artifact.content)
                    written.append(path)
                self._public(path.read_text(),names=[requirement.credential_requirement] if requirement.credential_requirement else [])
                previous_pin=prior_pins.get(requirement.requirement_id)
                original=next((r for r in snapshot.resources if previous_pin and r.resource_id==previous_pin.resource_id),None)
                metadata={'plan_id':plan.plan_id,'plan_version':plan.version,'requirement_id':requirement.requirement_id,
                    'spec_fingerprint':plan.spec_fingerprint,'acquisition_mode':requirement.acquisition_mode,'modality':requirement.modality,
                    'logical_resource_id':original.metadata.get('logical_resource_id',original.resource_id) if original else identifier,
                    'previous_resource_id':original.resource_id if original else None,
                    'parent_ids':list(dict.fromkeys(artifact.parent_ids+[resources[d].resource_id for d in requirement.dependencies])),
                    'parent_checksums':{resources[d].resource_id:resources[d].checksum for d in requirement.dependencies},
                    'creation_approval':approval_for(snapshot,s.PlannerAction.PREPARE_RESOURCES).model_dump(mode='json'),
                    'source_uri':requirement.source_uri,'source':requirement.source,
                    'configuration':requirement.parameters,'criteria':requirement.criteria.model_dump(mode='json'),
                    'creation_tool':requirement.handler,'model_metadata':runtime_metadata(self.agent),**artifact.metadata}
                record=s.ResourceRecord(resource_id=identifier,project_id=experiment.project_id,experiment_id=experiment.experiment_id,
                    experiment_version=experiment.version,resource_type=requirement.resource_type,purpose=requirement.purpose,
                    path_or_uri=str(path),source=requirement.source,version=str(int(original.version)+1 if original else 1),
                    checksum=checksum(path),metadata=metadata,status='PREPARED')
                ensure_public(record)
                resources[requirement.requirement_id]=record; records.append(record)
                kind='RESOURCE_REPAIRED' if original else 'RESOURCE_GENERATED' if requirement.handler=='synthetic' else 'RESOURCE_TRANSFORMED' if requirement.handler=='transform' else 'RESOURCE_ACQUIRED'
                events.append(self._event(experiment.project_id,kind,experiment,'Resource artifact prepared with provenance',resource_id=identifier,
                    resource_version=record.version,checksum=record.checksum,previous_resource_id=metadata['previous_resource_id']))
            mid=self.ledger.next_id('MANIFEST')
            mp=base.parent/(mid+'.json')
            manifest=ResourceManifest(manifest_id=mid,project_id=experiment.project_id,experiment_id=experiment.experiment_id,
                experiment_version=experiment.version,plan_id=plan.plan_id,plan_version=plan.version,spec_fingerprint=plan.spec_fingerprint,
                resources=[ResourcePin(requirement_id=r.metadata['requirement_id'],resource_id=r.resource_id,version=r.version,
                    checksum=r.checksum,path=r.path_or_uri,record_fingerprint=fingerprint(r),status=r.status) for r in resources.values()],
                validation_requirements={r.requirement_id:r.criteria for r in plan.resource_requirements},
                unresolved_warnings=plan.warnings,manifest_path=str(mp))
            ensure_public(manifest)
            with mp.open('x') as f: f.write(manifest.model_dump_json(indent=2)+'\n')
            written.append(mp)
            events.extend([self._event(experiment.project_id,'RESOURCE_MANIFEST_CREATED',experiment,'Exact immutable resource manifest registered',manifest=manifest.model_dump(mode='json')),
                self._event(experiment.project_id,'RESOURCE_PREPARATION_COMPLETED',experiment,'Resources prepared; independent readiness still required',manifest_id=mid)])
            def recheck():
                fresh=load_snapshot(self.ledger,experiment.project_id)
                if fresh!=snapshot: raise PreparationError('Ledger changed during preparation')
                self._gate(fresh)
            costs=[r.estimated_cost_usd for r in plan.resource_requirements]
            estimate=s.CostRecord(cost_id=self.ledger.next_id('COST'),project_id=experiment.project_id,
                experiment_id=experiment.experiment_id,experiment_version=experiment.version,category='resource preparation estimate',
                estimated_usd=sum(c or 0 for c in costs),actual_usd=0,
                metadata={'plan_id':plan.plan_id,'plan_version':plan.version,'estimate_only':True,'actual_known':False,
                    'unknown_estimates':any(c is None for c in costs),'model_invocation_cost':'UNKNOWN; transport supplies no verified billing'})
            self.ledger.add_many([*records,estimate,*events],check=recheck)
            return self._result(experiment,'PREPARED','Resources created; independent readiness required',plan_id=plan.plan_id,
                manifest_id=mid,resource_ids=[r.resource_id for r in resources.values()],repair_attempts=repair_attempts(load_snapshot(self.ledger,experiment.project_id)),warnings=plan.warnings)
        except Exception:
            for p in written: p.unlink(missing_ok=True)
            raise

    async def run(self, project_id, auditor=None):
        from autolab.readiness.service import ReadinessService
        auditor=auditor or ReadinessService(self.ledger)
        result=await self.prepare(project_id)
        while result.status=='PREPARED':
            report=await auditor.audit(project_id)
            if report.verdict!='REPAIR':
                return result.model_copy(update={'status':report.verdict.value,'readiness_id':report.readiness_id,
                    'summary':summary(result,report,[r for r in self.ledger.list_resources(project_id) if r.resource_id in result.resource_ids])})
            previous=current_plan(load_snapshot(self.ledger,project_id))
            if previous.version>=3 or repair_attempts(load_snapshot(self.ledger,project_id))>=2:
                report=auditor.record_exhausted(project_id,report)
                return result.model_copy(update={'status':'BLOCK','readiness_id':report.readiness_id,'summary':'Repair bound exhausted; control returned to Planner'})
            issues=report.metadata.get('issues') or [{'problem':x} for x in report.failed_checks]
            if not issues: issues=[{'problem':'Auditor REPAIR lacks specific issue; clarify'}]
            result=await self.prepare(project_id,previous=previous,issues=issues)
        return result


def summary(result, report=None, resources=()):
    rows=[f'Resources prepared: {len(result.resource_ids)}']
    rows.extend(f'- {r.resource_id}: {r.resource_type} — {r.purpose[:100]}' for r in resources)
    modes=[r.metadata.get('acquisition_mode') for r in resources]
    rows.extend([f'Generated: {sum(m in ("GENERATE","SYNTHESIZE") for m in modes)}',
        f'Downloaded: {modes.count("DOWNLOAD")}',
        f'Transformed: {sum(m in ("TRANSFORM","DERIVE") for m in modes)}',
        f'Manifest: {result.manifest_id}',f'Readiness: {report.verdict.value if report else "not audited"}',
        f'Repair attempts: {result.repair_attempts}',
        'Warnings: '+'; '.join((report.warnings if report else result.warnings)[:3]),
        'Experiment implementation generated: no; experiment executed: no'])
    return '\n'.join(rows)
