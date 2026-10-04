"""Completed execution requires immutable artifacts and exact run-scoped metrics."""
import hashlib
import json
from pathlib import Path
from autolab import schemas as s
from autolab.implementation.contract import RawObservation
from autolab.implementation.persistence import review_pins, audited_implementation_passes
from autolab.orchestration.state_machine import selected_experiment
from autolab.preparation.manifest import fingerprint
from .models import RunConfig


def digest(data): return hashlib.sha256(data).hexdigest()


def active_run(snapshot):
    finished={r.run_id for r in snapshot.runs}
    return next((e for e in reversed(snapshot.events) if e.actor=='experiment_runner'
        and e.event_type=='EXPERIMENT_RUN_STARTED' and e.target_id not in finished),None)


def valid_result(snapshot, run):
    try:
        if not run or run.status!=s.RunStatus.COMPLETED or not run.completed_at: return False
        spec=selected_experiment(snapshot)
        if not spec or (run.experiment_id,run.experiment_version)!=(spec.experiment_id,spec.version): return False
        config=RunConfig.model_validate(run.environment_metadata['config'])
        if (config.run_id,config.project_id,config.implementation_id)!=(run.run_id,run.project_id,run.implementation_id): return False
        implementation=next((i for i in snapshot.implementations if i.implementation_id==run.implementation_id),None)
        if not implementation or not audited_implementation_passes(snapshot,implementation): return False
        if config.dependency_pins!=review_pins(snapshot,implementation): return False
        if (config.implementation_hash!=implementation.code_version or config.seed!=run.random_seed
            or config.manifest_id!=config.dependency_pins['manifest_id']
            or config.manifest_hash!=config.dependency_pins['manifest_fingerprint']
            or run.input_manifest.get('dependency_pins')!=config.dependency_pins
            or run.output_manifest.get('partial',False)): return False
        root=Path(config.working_directory)
        if root.resolve()!=root or not root.is_dir(): return False
        artifacts=run.output_manifest['artifacts']
        contents={}
        for name,pin in artifacts.items():
            path=Path(pin['path'])
            if path.resolve()!=path or not path.is_relative_to(root) or path.stat().st_size!=pin['size']: return False
            contents[name]=path.read_bytes()
            if digest(contents[name])!=pin['sha256']: return False
        if json.loads(contents['config.json'])!=config.model_dump(mode='json'): return False
        raw=[json.loads(line) for line in contents['raw_outputs.jsonl'].splitlines()]
        if not raw or len(raw)!=run.output_manifest['observation_count']: return False
        for item in raw:
            if (item['run_id'],item['experiment_id'],item['experiment_version'],item['implementation_hash'])!=(run.run_id,run.experiment_id,run.experiment_version,config.implementation_hash): return False
            if item['resource_pins']!=config.dependency_pins['resource_pins']: return False
            RawObservation.model_validate(item['observation'],strict=True)
        metrics=[m for m in snapshot.metrics if m.run_id==run.run_id]
        saved=json.loads(contents['metrics.json'])
        if [m.model_dump(mode='json') for m in metrics]!=saved: return False
        expected=run.output_manifest['metric_keys']
        keys=[[m.metric_name,m.metadata.get('condition'),m.metadata.get('role')] for m in metrics]
        if keys!=expected or len({tuple(k) for k in keys})!=len(keys): return False
        if set(m.metric_name for m in metrics)!={spec.primary_metric,*spec.secondary_metrics}: return False
        if not any(m.metric_name==spec.primary_metric and m.metadata.get('role')=='primary' for m in metrics): return False
        for m in metrics:
            if (m.project_id,m.experiment_id,m.experiment_version)!=(run.project_id,run.experiment_id,run.experiment_version): return False
            if m.metadata.get('raw_sha256')!=artifacts['raw_outputs.jsonl']['sha256'] or m.metadata.get('denominator',0)<1: return False
        completed=next((e for e in reversed(snapshot.events) if e.actor=='experiment_runner'
            and e.event_type=='EXPERIMENT_RUN_COMPLETED' and e.target_id==run.run_id),None)
        return bool(completed and completed.payload.get('run_fingerprint')==fingerprint(run)
            and completed.payload.get('metric_fingerprints')==[fingerprint(m) for m in metrics])
    except (OSError,ValueError,TypeError,KeyError,AttributeError): return False
