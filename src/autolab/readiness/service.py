"""Independent audit; deterministic facts cannot be overruled by semantic PASS."""
import json
from pathlib import Path
from autolab import schemas as s
from autolab.feasibility.persistence import ensure_public
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_experiment, approval_for
from autolab.planner.service import runtime_metadata
from autolab.preparation.models import PreparationError
from autolab.preparation.manifest import current_manifest, current_plan, fingerprint, manifest_errors, repair_attempts
from autolab.preparation.service import PreparationService
from .agent import OmnigentReadinessAuditor
from .validators import ValidatorRegistry


class ReadinessService:
    def __init__(self, ledger, agent=None, *, validators=None):
        self.ledger=ledger; self.agent=agent or OmnigentReadinessAuditor()
        self.validators=validators or ValidatorRegistry()

    def _event(self, report, kind, **payload):
        return s.EventRecord(event_id=self.ledger.next_id('EVENT'),project_id=report.project_id,event_type=kind,
            actor='readiness',target_type='readiness_reports',target_id=report.readiness_id,
            summary=f'Independent resource readiness {kind}',payload={'experiment_id':report.experiment_id,
                'experiment_version':report.experiment_version,'readiness_id':report.readiness_id,**payload})

    async def audit(self, project_id):
        before=load_snapshot(self.ledger,project_id)
        PreparationService(self.ledger)._gate(before,readiness=True)
        experiment=selected_experiment(before); manifest=current_manifest(before); plan=current_plan(before)
        if not manifest: raise PreparationError('A current persisted ResourceManifest is required for readiness')
        assignment={'readiness_id':self.ledger.next_id('READY'),'project_id':project_id,
            'experiment_id':experiment.experiment_id,'experiment_version':experiment.version}
        started=s.ReadinessReport(**assignment,resource_readiness=False,technical_readiness=False,
            scientific_readiness=False,quality_readiness=False,verdict='BLOCK')
        self.ledger.add_many([self._event(started,'RESOURCE_VALIDATION_STARTED'),self._event(started,'READINESS_AUDIT_STARTED')])
        snapshot=load_snapshot(self.ledger,project_id)
        integrity=manifest_errors(snapshot,manifest)
        evidence=self.validators.validate(snapshot,manifest)
        for error in integrity:
            evidence.findings.append({'resource_id':None,'check':'manifest_integrity','passed':False,'detail':error,'gate':'resource'})
        # Clip each sample, stratified summary and provenance; raw large data never enters audit context.
        summaries=[]; remaining_samples=24
        for item in evidence.summaries:
            compact=dict(item)
            for key in ('samples','suspicious_samples'):
                samples=compact.get(key,[])[:remaining_samples]
                compact[key]=[json.loads(json.dumps(x)) if len(json.dumps(x))<=2200 else {'truncated_sample':json.dumps(x)[:2200]} for x in samples]
                remaining_samples-=len(samples)
            if 'sample' in compact and len(json.dumps(compact['sample']))>12000: compact['sample']={'truncated':json.dumps(compact['sample'])[:12000]}
            summaries.append(compact)
        responses=next((e.payload['responses'] for e in reversed(snapshot.events)
            if e.actor=='preparation' and e.event_type=='PREPARATION_REPAIR_RESPONSES'
            and e.target_id==experiment.experiment_id and e.payload.get('plan_id')==plan.plan_id
            and e.payload.get('plan_version')==plan.version),[r.model_dump(mode='json') for r in plan.issue_responses])
        context={'experiment_spec':experiment.model_dump(mode='json'),
            'current_approval':approval_for(snapshot,s.PlannerAction.PREPARE_RESOURCES).model_dump(mode='json'),
            'manifest_id':manifest.manifest_id,
            'resource_pins':[{**p.model_dump(mode='json'),'path':Path(p.path).name} for p in manifest.resources],
            'acceptance_criteria':{k:v.model_dump(mode='json') for k,v in manifest.validation_requirements.items()},
            'deterministic_findings':evidence.findings,'resource_summaries':summaries,
            'provenance':[{'resource_id':r.resource_id,'version':r.version,'source':r.source,'modality':r.metadata.get('modality'),
                'generation_specification':str(r.metadata.get('specification',''))[:2000], 'seed':r.metadata.get('seed'),
                'creation_tool':r.metadata.get('creation_tool'),'parent_ids':r.metadata.get('parent_ids'),
                'license':r.metadata.get('license')} for r in snapshot.resources if r.resource_id in {p.resource_id for p in manifest.resources}],
            'preparation_plan':plan.model_dump(mode='json',exclude={'resource_requirements':{'__all__':{'parameters'}}}),
            'repair_responses':responses,
            'limitations':plan.warnings+['Semantic sampling is bounded and does not establish population-wide quality or statistical power.']}
        ensure_public(context)
        try:
            proposed=await self.agent.audit(context,assignment)
            report=s.ReadinessReport.model_validate(proposed.model_dump() if isinstance(proposed,s.ReadinessReport) else proposed)
            ensure_public(report)
            if any(getattr(report,k)!=v for k,v in assignment.items()): raise PreparationError('Auditor changed assigned report bindings')
            if len(report.model_dump_json())>40000: raise PreparationError('Auditor output exceeds report bound')
            if 'resource_pins' in report.metadata and report.metadata['resource_pins']!=context['resource_pins']:
                raise PreparationError('Auditor resource versions do not match current pins')
            semantic=report.metadata.get('semantic_findings')
            if not isinstance(semantic,list) or not semantic: raise PreparationError('Auditor must preserve independent semantic findings')
            valid_ids={p.resource_id for p in manifest.resources}
            def check_ids(value):
                if isinstance(value,dict):
                    for k,v in value.items():
                        if k=='resource_id' and v not in valid_ids: raise PreparationError('Auditor fabricated resource identity')
                        if k=='resource_ids' and (not isinstance(v,list) or not set(v)<=valid_ids): raise PreparationError('Auditor fabricated resource identities')
                        check_ids(v)
                elif isinstance(value,list):
                    for v in value: check_ids(v)
            check_ids(report.metadata)
            if report.verdict=='PASS' and (report.failed_checks or not all((report.resource_readiness,report.technical_readiness,report.scientific_readiness,report.quality_readiness))):
                raise PreparationError('Semantic PASS conflicts with readiness gates')
            failed=[f for f in evidence.findings if not f['passed']]
            gates={g:getattr(report,g+'_readiness') and not any(f['gate']==g for f in failed) for g in ('resource','technical','scientific','quality')}
            verdict='REPAIR' if failed and report.verdict=='PASS' else report.verdict.value
            checks=list(dict.fromkeys(report.failed_checks+[f"{f['resource_id'] or 'manifest'}: {f['check']} — {f['detail']}" for f in failed]))
            issues=report.metadata.get('issues',[])
            if not isinstance(issues,list): raise PreparationError('Readiness issues must be structured list')
            metadata={**report.metadata,'auditor_role':'readiness','manifest_id':manifest.manifest_id,
                'manifest_fingerprint':fingerprint(manifest),'spec_fingerprint':manifest.spec_fingerprint,
                'resource_pins':[p.model_dump(mode='json') for p in manifest.resources],
                'deterministic_findings':evidence.findings,'semantic_findings':semantic,'repair_count':repair_attempts(snapshot),
                'issues':issues+[{'problem':f['detail'],'check':f['check'],'resource_ids':[f['resource_id']] if f['resource_id'] else []} for f in failed],
                'model_metadata':runtime_metadata(self.agent)}
            report=s.ReadinessReport(**assignment,**{g+'_readiness':v for g,v in gates.items()},verdict=verdict,
                failed_checks=checks,warnings=report.warnings+manifest.unresolved_warnings,recommendations=report.recommendations,metadata=metadata)
            ensure_public(report)
            kind={'PASS':'READINESS_PASSED','REPAIR':'READINESS_REPAIR_REQUESTED','BLOCK':'READINESS_BLOCKED'}[report.verdict.value]
            def recheck():
                fresh=load_snapshot(self.ledger,project_id)
                if fresh!=snapshot: raise PreparationError('Ledger changed during independent audit')
                # Artifact changes during audit invalidate PASS. Failed audits may still persist useful findings.
                if report.verdict=='PASS' and manifest_errors(fresh,manifest): raise PreparationError('Resources changed during independent audit')
                PreparationService(self.ledger)._gate(fresh,readiness=True)
            self.ledger.add_many([report,self._event(report,kind,manifest_id=manifest.manifest_id,repair_count=metadata['repair_count'])],check=recheck)
            return report
        except Exception:
            self.ledger.add_event(self._event(started,'READINESS_AUDIT_FAILED',reason='Malformed or failed independent audit; no new PASS persisted'))
            raise PreparationError('Readiness audit failed; prior records retained and no new readiness authorization granted') from None

    def record_exhausted(self, project_id, previous):
        snapshot=load_snapshot(self.ledger,project_id)
        if (repair_attempts(snapshot)<2 or previous.verdict!='REPAIR'
            or not snapshot.readiness or snapshot.readiness[-1]!=previous):
            raise PreparationError('Exhaustion requires the current independent REPAIR and two consumed attempts')
        report=s.ReadinessReport.model_validate({**previous.model_dump(mode='json'),'readiness_id':self.ledger.next_id('READY'),
            'created_at':s.utc_now(),'verdict':'BLOCK',
            'metadata':{**previous.metadata,'repair_count':repair_attempts(snapshot),
                'verdict_origin':'deterministic_repair_limit; no new independent model audit',
                'original_independent_readiness_id':previous.readiness_id},
            'recommendations':previous.recommendations+['Repair limit of two attempts exhausted; return to Planner']})
        self.ledger.add_many([report,self._event(report,'READINESS_BLOCKED',reason='Repair limit exhausted')])
        return report
