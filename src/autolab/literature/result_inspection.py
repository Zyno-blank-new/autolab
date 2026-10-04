"""Read existing scientific artifacts with their original hashes; never rerun."""
import json
from pathlib import Path
from autolab.analysis.result_summary import build_result_summary
from autolab.orchestration.state_machine import current_run
from autolab.preparation.manifest import checksum
from .screening import EvidenceOutputError


def inspect_result(snapshot):
    summary = build_result_summary(snapshot)
    run = current_run(snapshot)
    artifact = run.output_manifest['artifacts']['raw_outputs.jsonl']
    data = Path(artifact['path']).read_bytes()
    from autolab.runtime.persistence import digest
    if digest(data) != artifact['sha256']:
        raise EvidenceOutputError('Raw artifact changed during evidence inspection')
    raw = [json.loads(line)['observation'] for line in data.splitlines()]
    if len(raw) > 24:
        raise EvidenceOutputError('Complete observation inspection exceeds bounded MVP; request targeted evidence instead')
    groups = {}
    for observation in raw:
        groups.setdefault(observation['condition'], []).append(observation['sample_id'])
    resources = []
    for resource in snapshot.resources:
        if (resource.experiment_id, resource.experiment_version) != (run.experiment_id, run.experiment_version):
            continue
        path = Path(resource.path_or_uri)
        if path.is_symlink() or path.resolve() != path or not path.is_file() or path.stat().st_size > 100000:
            raise EvidenceOutputError('Original input artifact unavailable within inspection bound')
        original_hash = checksum(path)
        if original_hash != resource.checksum:
            raise EvidenceOutputError('Original input artifact hash changed')
        data = json.loads(path.read_bytes())
        resources.append({'resource_id': resource.resource_id, 'sha256': original_hash, 'original_data': data})
    if len(json.dumps(resources)) > 12000:
        raise EvidenceOutputError('Original input packet exceeds inspection bound')
    lists = list(groups.values())
    from autolab.orchestration.state_machine import current_analysis
    return {'run_id': run.run_id, 'analysis_id': current_analysis(snapshot).analysis_id, 'raw_sha256': artifact['sha256'],
        'condition_sample_ids': groups, 'matched_identity_and_order': bool(lists) and all(x == lists[0] for x in lists),
        'unique_ids_per_condition': {k: len(set(v)) == len(v) for k, v in groups.items()},
        'observations': raw, 'original_resources': resources,
        'scope': 'Exact persisted observations and original hash bindings only; no population inference or independent source-code reproduction'}
