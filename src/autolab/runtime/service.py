"""One offline deterministic attempt; no agent calls, redesign or auto-repair."""
import json
import math
import platform
import re
import time
from pathlib import Path
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.implementation.contract import RawObservation
from autolab.implementation.models import ImplementationPlan
from autolab.implementation.persistence import review_pins, audited_implementation_passes
from autolab.implementation.validation import read_sources, source_hash
from autolab.orchestration.budget import calculate_budget, calculate_time
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import (selected_experiment,current_implementation,
    approval_for,charter_fingerprint)
from autolab.preparation.manifest import current_manifest, fingerprint
from .models import RunConfig, RuntimeErrorRecord, ProcessReceipt
from .persistence import digest
from .process import execute


class ExperimentRuntime:
    def __init__(self, ledger, *, adapters=None, root=PROJECT_ROOT):
        self.ledger=ledger; self.adapters=adapters or {}; self.root=Path(root).resolve()

    def event(self, project, kind, target, **payload):
        return s.EventRecord(event_id=self.ledger.next_id('EVENT'),project_id=project,event_type=kind,
            actor='experiment_runner',target_type='runs' if target else 'projects',target_id=target or project,
            summary=kind+'; deterministic execution only',payload=payload)

    def gate(self, snapshot):
        decision=s.NextDecision(decision_id='DEC_RUNTIME_CHECK',project_id=snapshot.charter.project_id,
            action='RUN_EXPERIMENT',target_agent='experiment_runner',reason='Deterministic execution preflight',
            remaining_budget_usd=calculate_budget(snapshot).remaining_budget_usd)
        valid=DecisionValidator().validate(decision,snapshot)
        if not valid.valid: raise RuntimeErrorRecord('; '.join(valid.reasons))
        spec=selected_experiment(snapshot); record=current_implementation(snapshot)
        pins=review_pins(snapshot,record)
        adapter=self.adapters.get(pins['spec_fingerprint'])
        if not adapter or adapter.spec_hash!=pins['spec_fingerprint']: raise RuntimeErrorRecord('Reviewed runtime adapter missing for exact spec')
        if adapter.seed not in record.metadata['plan']['seeds']: raise RuntimeErrorRecord('Runtime seed not in audited plan')
        adapter.validate_spec(spec,ImplementationPlan.model_validate(record.metadata['plan']))
        files=read_sources(record)
        if source_hash(files)!=pins['code_hash']: raise RuntimeErrorRecord('Audited code hash mismatch')
        resources={}; hashes={}
        for pin in pins['resource_pins']:
            path=Path(pin['path'])
            if path.resolve()!=path or not path.is_file() or path.stat().st_size>2000000:
                raise RuntimeErrorRecord('Resource path/size policy failed')
            data=path.read_bytes()
            if digest(data)!=pin['checksum']: raise RuntimeErrorRecord('Resource checksum mismatch')
            resources[pin['resource_id']]=json.loads(data); hashes[pin['resource_id']]=digest(data)
        return spec,record,pins,adapter,files,resources,hashes

    async def run(self, project_id, *, timeout_seconds=10, max_output_bytes=262144, max_log_bytes=8192):
        before=load_snapshot(self.ledger,project_id)
        try: spec,record,pins,adapter,files,resources,hashes=self.gate(before)
        except (ValueError,OSError) as exc:
            self.ledger.add_event(self.event(project_id,'EXPERIMENT_RUN_REJECTED',None,reason=str(exc)[:1000]))
            raise RuntimeErrorRecord(str(exc)) from None
        scope=approval_for(before,s.PlannerAction.RUN_EXPERIMENT)
        remaining=calculate_time(before).remaining_minutes
        if timeout_seconds>scope.max_runtime_minutes*60 or (remaining is not None and timeout_seconds>remaining*60):
            raise RuntimeErrorRecord('Timeout exceeds approved runtime envelope')
        run_id=self.ledger.next_id('RUN')
        if not re.fullmatch(r'[A-Za-z0-9_-]+',spec.experiment_id): raise RuntimeErrorRecord('Unsafe experiment directory identity')
        root=self.root/'experiments'/spec.experiment_id/'runs'/run_id
        if root.resolve()!=root: raise RuntimeErrorRecord('Unconfined run directory')
        config=RunConfig(run_id=run_id,project_id=project_id,experiment_id=spec.experiment_id,
            experiment_version=spec.version,implementation_id=record.implementation_id,implementation_hash=record.code_version,
            manifest_id=pins['manifest_id'],manifest_hash=pins['manifest_fingerprint'],dependency_pins=pins,
            charter_hash=charter_fingerprint(before.charter),adapter_id=adapter.adapter_id,seed=adapter.seed,
            timeout_seconds=timeout_seconds,working_directory=str(root),max_output_bytes=max_output_bytes,
            max_log_bytes=max_log_bytes,max_observations=adapter.observation_limit(resources),deterministic=adapter.deterministic)
        root.mkdir(parents=True,exist_ok=False)
        def write(name, data):
            data=data if isinstance(data,bytes) else data.encode()
            path=root/name
            with path.open('xb') as out: out.write(data)
            return {'path':str(path),'sha256':digest(data),'size':len(data)}
        artifacts={'config.json':write('config.json',config.model_dump_json(indent=2))}
        started=s.utc_now(); start_clock=time.monotonic()
        initial=[self.event(project_id,'EXPERIMENT_RUN_REQUESTED',run_id,config=config.model_dump(mode='json')),
            self.event(project_id,'RESOURCE_INTEGRITY_VERIFIED',run_id,resource_pins=pins['resource_pins']),
            self.event(project_id,'IMPLEMENTATION_INTEGRITY_VERIFIED',run_id,code_hash=record.code_version),
            self.event(project_id,'EXPERIMENT_RUN_STARTED',run_id,config=config.model_dump(mode='json'),started_at=started.isoformat())]
        def check_start():
            fresh=load_snapshot(self.ledger,project_id)
            self.gate(fresh)
            if fresh!=before: raise RuntimeErrorRecord('State changed during preflight')
        self.ledger.add_many(initial,check=check_start)
        receipt=ProcessReceipt(); metric_receipt=ProcessReceipt(); observations=[]; metrics=[]; error=None; error_type=None
        status=s.RunStatus.FAILED
        try:
            receipt=await execute({'mode':'run','files':files,'context':adapter.context(spec,resources,hashes)},config)
            if receipt.cancelled: status=s.RunStatus.CANCELLED; raise RuntimeErrorRecord('Execution cancelled')
            if receipt.timed_out: status=s.RunStatus.TIMED_OUT; raise RuntimeErrorRecord('Execution timed out')
            if receipt.output_exceeded: raise RuntimeErrorRecord('Execution output limit exceeded')
            if receipt.exit_status!=0:
                message=next((m for m in receipt.messages if m.get('kind')=='error'),{})
                error_type=message.get('error_type','ChildProcessError')
                raise RuntimeErrorRecord(message.get('detail','Execution process failed'))
            completed=[m for m in receipt.messages if m.get('kind')=='completed']
            if len(completed)!=1 or (completed[0].get('experiment_id'),completed[0].get('experiment_version'))!=(spec.experiment_id,spec.version):
                raise RuntimeErrorRecord('Malformed or incomplete raw output envelope')
            raw=[m['observation'] for m in receipt.messages if m.get('kind')=='observation']
            if len(raw)>config.max_observations: raise RuntimeErrorRecord('Observation limit exceeded')
            observations=[RawObservation.model_validate(o,strict=True) for o in raw]
            if any(count<0 for observation in observations for count in observation.counts.values()):
                raise RuntimeErrorRecord('Negative observed usage counter')
            plan=ImplementationPlan.model_validate(record.metadata['plan'])
            jobs=adapter.metric_jobs(observations,resources,plan)
            if not jobs: raise RuntimeErrorRecord('Primary metric absent')
            registered={spec.primary_metric,*spec.secondary_metrics}
            if set(j.metric_name for j in jobs)!=registered or any(j.component!=plan.metrics.get(j.metric_name) for j in jobs):
                raise RuntimeErrorRecord('Unregistered or unaudited metric component')
            if len({(j.metric_name,j.condition) for j in jobs})!=len(jobs): raise RuntimeErrorRecord('Duplicate metric group')
            if any(j.role!=('primary' if j.metric_name==spec.primary_metric else 'secondary') for j in jobs):
                raise RuntimeErrorRecord('Metric role mismatch')
            deadline=config.timeout_seconds-(time.monotonic()-start_clock)
            if deadline<=0: status=s.RunStatus.TIMED_OUT; raise RuntimeErrorRecord('Metric deadline exhausted')
            metric_receipt=await execute({'mode':'metrics','files':files,'jobs':[j.model_dump(mode='json') for j in jobs]},config,timeout_seconds=deadline)
            if metric_receipt.timed_out: status=s.RunStatus.TIMED_OUT; raise RuntimeErrorRecord('Metric execution timed out')
            if metric_receipt.cancelled: status=s.RunStatus.CANCELLED; raise RuntimeErrorRecord('Metric execution cancelled')
            if metric_receipt.exit_status!=0 or metric_receipt.output_exceeded: raise RuntimeErrorRecord('Metric computation failed')
            messages=[m for m in metric_receipt.messages if m.get('kind')=='metrics']
            values=messages[0]['values'] if len(messages)==1 else []
            if len(values)!=len(jobs): raise RuntimeErrorRecord('Missing metric output')
            # Independent, trusted oracle reads validated raw observations.
            for job,value in zip(jobs,values):
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): raise RuntimeErrorRecord('Nonfinite metric')
                if not math.isclose(value,adapter.independently_recompute(job,observations),rel_tol=1e-12,abs_tol=1e-12):
                    raise RuntimeErrorRecord('Audited metric differs from independent raw recomputation')
            status=s.RunStatus.COMPLETED
        except Exception as exc:
            error_type=error_type or type(exc).__name__; error=str(exc)[:1000]
        # Preserve even malformed/failed/partial emitted observations as audit
        # evidence. Only validated complete observations authorize final metrics.
        emitted=[m['observation'] for m in receipt.messages if m.get('kind')=='observation' and 'observation' in m]
        raw_bytes=bytearray(); persisted_count=0
        for observation in emitted:
            envelope={'run_id':run_id,'experiment_id':spec.experiment_id,'experiment_version':spec.version,
                'implementation_hash':record.code_version,'resource_pins':pins['resource_pins'],'observation':observation}
            line=(json.dumps(envelope,allow_nan=False,separators=(',',':'))+'\n').encode()
            if len(raw_bytes)+len(line)>config.max_output_bytes:
                status=s.RunStatus.FAILED;error='Raw artifact output limit exceeded; remaining observations not published'
                error_type='OutputLimitError';break
            raw_bytes.extend(line);persisted_count+=1
        artifacts['raw_outputs.jsonl']=write('raw_outputs.jsonl',bytes(raw_bytes))
        artifacts['stdout.log']=write('stdout.log',receipt.stdout.encode()[:config.max_log_bytes])
        artifacts['stderr.log']=write('stderr.log',receipt.stderr.encode()[:config.max_log_bytes])
        artifacts['metric_stdout.log']=write('metric_stdout.log',metric_receipt.stdout.encode()[:config.max_log_bytes])
        artifacts['metric_stderr.log']=write('metric_stderr.log',metric_receipt.stderr.encode()[:config.max_log_bytes])
        if status==s.RunStatus.COMPLETED:
            fresh=load_snapshot(self.ledger,project_id)
            if (not audited_implementation_passes(fresh,record) or review_pins(fresh,record)!=pins
                or not approval_for(fresh,s.PlannerAction.RUN_EXPERIMENT)
                or charter_fingerprint(fresh.charter)!=config.charter_hash
                or any(d.action==s.PlannerAction.STOP for d in fresh.decisions)):
                status=s.RunStatus.FAILED; error='Dependencies or approval changed during execution'; error_type='IntegrityError'
            else:
                for job,value in zip(jobs,values):
                    metrics.append(s.MetricRecord(metric_id=self.ledger.next_id('METRIC'),project_id=project_id,
                        experiment_id=spec.experiment_id,experiment_version=spec.version,run_id=run_id,
                        metric_name=job.metric_name,metric_value=float(value),unit=job.unit,
                        metadata={'role':job.role,'condition':job.condition,'denominator':job.denominator,
                            'support':job.support,'component':job.component,'method_version':adapter.adapter_id,
                            'implementation_hash':record.code_version,'raw_sha256':artifacts['raw_outputs.jsonl']['sha256'],
                            'independent_recomputation':True}))
        artifacts['metrics.json']=write('metrics.json',json.dumps([m.model_dump(mode='json') for m in metrics],indent=2,allow_nan=False))
        ended=s.utc_now(); duration=time.monotonic()-start_clock
        usage={}; invalid_usage=[]
        for emitted_observation in emitted:
            try: observation=RawObservation.model_validate(emitted_observation,strict=True)
            except ValueError: continue
            for name,count in observation.counts.items():
                if count<0: invalid_usage.append(name);continue
                usage[name]=usage.get(name,0)+count
        if invalid_usage: usage['invalid_usage_counters']=sorted(set(invalid_usage))
        usage.update({'raw_observations':len(emitted),'attempts':1,'whole_experiment_retries':0})
        run=s.ExperimentRun(run_id=run_id,project_id=project_id,experiment_id=spec.experiment_id,
            experiment_version=spec.version,implementation_id=record.implementation_id,started_at=started,completed_at=ended,
            status=status,random_seed=adapter.seed,cost_usd=None,error_message=error,
            environment_metadata={'config':config.model_dump(mode='json'),'duration_seconds':duration,
                'python_version':platform.python_version(),'framework_version':'autolab-phase10-v1',
                'framework_source_sha256':digest(json.dumps({p.name:p.read_text() for p in sorted(Path(__file__).parent.glob('*.py'))},
                    sort_keys=True,separators=(',',':')).encode()),
                'exit_status':receipt.exit_status,'metric_exit_status':metric_receipt.exit_status,
                'error_type':error_type,'usage':usage,'actual_cost_status':'UNKNOWN','provider_inference':'none',
                'isolation':'Restricted offline Python profile; not an OS sandbox'},
            input_manifest={'dependency_pins':pins,'resource_hashes':hashes},
            output_manifest={'artifacts':artifacts,'observation_count':persisted_count,'emitted_observation_count':len(emitted),
                'unpublished_observation_count':len(emitted)-persisted_count,'partial':status!=s.RunStatus.COMPLETED,
                'metric_keys':[[m.metric_name,m.metadata['condition'],m.metadata['role']] for m in metrics]})
        cost=s.CostRecord(cost_id=self.ledger.next_id('COST'),project_id=project_id,experiment_id=spec.experiment_id,
            experiment_version=spec.version,category='experiment_runtime',actual_usd=None,
            metadata={'run_id':run_id,'actual_known':False,'actual_cost_status':'UNKNOWN','usage':usage,
                      'reason':'No trustworthy billable local execution cost measurement; estimates not actuals'})
        events=[self.event(project_id,'RAW_OUTPUTS_PERSISTED',run_id,artifact=artifacts['raw_outputs.jsonl'],partial=run.output_manifest['partial'])]
        if metrics:
            events.extend([self.event(project_id,'METRICS_COMPUTED',run_id,method='audited Python + independent raw oracle'),
                           self.event(project_id,'METRICS_PERSISTED',run_id,metric_ids=[m.metric_id for m in metrics])])
        terminal='EXPERIMENT_RUN_'+status.value
        events.append(self.event(project_id,terminal,run_id,run_fingerprint=fingerprint(run),
            metric_fingerprints=[fingerprint(m) for m in metrics],duration_seconds=duration,error=error))
        # Final identity is inserted once. Active state is represented by events,
        # respecting the ledger's existing append-only run table.
        def final_integrity():
            if run.status!=s.RunStatus.COMPLETED: return
            fresh=load_snapshot(self.ledger,project_id)
            if (not audited_implementation_passes(fresh,record) or review_pins(fresh,record)!=pins
                or not approval_for(fresh,s.PlannerAction.RUN_EXPERIMENT)
                or any(d.action==s.PlannerAction.STOP for d in fresh.decisions)):
                raise RuntimeErrorRecord('Dependencies changed before atomic finalization')
        try:
            self.ledger.add_many([run,*metrics,cost,*events],check=final_integrity)
        except RuntimeErrorRecord as exc:
            # Do not overwrite already-written evidence. Any computed artifact
            # remains explicitly partial/unpublished; no final MetricRecord.
            run=run.model_copy(update={'status':s.RunStatus.FAILED,'error_message':str(exc),
                'output_manifest':{**run.output_manifest,'partial':True,'metric_keys':[]},
                'environment_metadata':{**run.environment_metadata,'error_type':'IntegrityError'}})
            self.ledger.add_many([run,cost,self.event(project_id,'RAW_OUTPUTS_PERSISTED',run_id,
                artifact=artifacts['raw_outputs.jsonl'],partial=True),self.event(project_id,'EXPERIMENT_RUN_FAILED',run_id,
                run_fingerprint=fingerprint(run),metric_fingerprints=[],error=str(exc))])
        return run
