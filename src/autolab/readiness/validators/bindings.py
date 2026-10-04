"""Small declarative cross-resource foreign-key validator, configured by callers."""
import json
from pathlib import Path
from .base import ValidationEvidence


class BindingValidator:
    def __init__(self, rules):
        # Rules are operator/contract configuration, never executable expressions.
        self.rules=list(rules)

    def validate_collection(self, snapshot, manifest, evidence: ValidationEvidence):
        pins={p.requirement_id:p for p in manifest.resources}
        records={r.resource_id:r for r in snapshot.resources}
        for rule in self.rules:
            source=pins.get(rule['source_requirement']); target=pins.get(rule['target_requirement'])
            if not source or not target: continue  # Manifest coverage check handles absent resources.
            record=records[source.resource_id]
            try:
                left=json.loads(Path(source.path).read_text()); right=json.loads(Path(target.path).read_text())
                if not isinstance(left,list) or not isinstance(right,list): raise ValueError('Rows needed')
                sf=rule['source_fields']; tf=rule['target_fields']
                right=[r for r in right if all(r.get(k)==v for k,v in rule.get('target_filter',{}).items())]
                keys={json.dumps([r[k] for k in tf],sort_keys=True) for r in right}
                rows=[r for r in left if all(r.get(k)==v for k,v in rule.get('source_filter',{}).items())]
                okay=all(json.dumps([r[k] for k in sf],sort_keys=True) in keys for r in rows)
            except (OSError,ValueError,KeyError,TypeError): okay=False
            evidence.add(record,'resource_binding',okay,'Declared cross-resource key references','scientific')
