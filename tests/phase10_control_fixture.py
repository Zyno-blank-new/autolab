"""Explicit mocked result receipts for existing control-plane tests only."""
import json
from pathlib import Path
from autolab import schemas as s
from autolab.runtime.models import RunConfig
from autolab.runtime.persistence import digest
from autolab.implementation.persistence import review_pins
from autolab.orchestration.state_machine import current_implementation, selected_experiment, charter_fingerprint
from autolab.preparation.manifest import fingerprint


def pin_result_fixture(snapshot, run):
    record=current_implementation(snapshot); spec=selected_experiment(snapshot); pins=review_pins(snapshot,record)
    root=Path(record.metadata['artifact_path'])/'mock-result'; root.mkdir()
    config=RunConfig(run_id=run.run_id,project_id=run.project_id,experiment_id=run.experiment_id,
        experiment_version=run.experiment_version,implementation_id=record.implementation_id,implementation_hash=record.code_version,
        manifest_id=pins['manifest_id'],manifest_hash=pins['manifest_fingerprint'],dependency_pins=pins,
        charter_hash=charter_fingerprint(snapshot.charter),adapter_id='mock-control-plane-v1',seed=run.random_seed or 0,
        working_directory=str(root),max_observations=1)
    raw={'run_id':run.run_id,'experiment_id':run.experiment_id,'experiment_version':run.experiment_version,
        'implementation_hash':record.code_version,'resource_pins':pins['resource_pins'],
        'observation':{'condition':'fixture','sample_id':'fixture-1','outputs':{'value':1.0},'status':'success'}}
    artifacts={}
    def write(name,contents):
        data=contents.encode(); path=root/name; path.write_bytes(data)
        artifacts[name]={'path':str(path),'size':len(data),'sha256':digest(data)}
    write('config.json',config.model_dump_json())
    write('raw_outputs.jsonl',json.dumps(raw)+'\n')
    metrics=[s.MetricRecord(metric_id='METRIC_CONTROL_'+str(i),project_id=run.project_id,experiment_id=run.experiment_id,
        experiment_version=run.experiment_version,run_id=run.run_id,metric_name=name,metric_value=1.0,
        metadata={'condition':'fixture','role':'primary' if name==spec.primary_metric else 'secondary','denominator':1,
                  'raw_sha256':artifacts['raw_outputs.jsonl']['sha256']}) for i,name in enumerate([spec.primary_metric,*spec.secondary_metrics])]
    write('metrics.json',json.dumps([m.model_dump(mode='json') for m in metrics]))
    run=run.model_copy(update={'implementation_id':record.implementation_id,
        'environment_metadata':{'config':config.model_dump(mode='json')},
        'input_manifest':{'dependency_pins':pins},
        'output_manifest':{'artifacts':artifacts,'observation_count':1,
            'metric_keys':[[m.metric_name,'fixture',m.metadata['role']] for m in metrics]}})
    event=s.EventRecord(event_id='EVENT_CONTROL_RESULT',project_id=run.project_id,event_type='EXPERIMENT_RUN_COMPLETED',
        actor='experiment_runner',target_type='runs',target_id=run.run_id,summary='Explicit mocked control-plane receipt; no execution',
        payload={'run_fingerprint':fingerprint(run),'metric_fingerprints':[fingerprint(m) for m in metrics]})
    return snapshot.model_copy(update={'runs':[run],'metrics':metrics,'events':[*snapshot.events,event]})
