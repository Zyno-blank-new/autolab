"""Allowlisted projection and seeded group-preserving splits only."""
import json
import random
from autolab.preparation.models import PreparationError
from .base import Artifact, MAX_BYTES, require_keys, safe_path


class TransformHandler:
    def prepare(self, requirement, context):
        p=requirement.parameters
        require_keys(p, {'parent_requirement','operation','fields','seed','group_field','split_field','train_fraction'},
            {'parent_requirement','operation'})
        parent=context['resources'].get(p['parent_requirement'])
        if not parent or p['parent_requirement'] not in requirement.dependencies:
            raise PreparationError('Transform needs an explicit prepared dependency')
        path=safe_path(parent.path_or_uri,context['allowed_roots'])
        data=json.loads(path.read_text())
        if not isinstance(data,list) or not all(isinstance(r,dict) for r in data):
            raise PreparationError('Transform requires structured rows')
        if p['operation']=='project':
            fields=p.get('fields')
            if not isinstance(fields,list) or not fields: raise PreparationError('Projection needs fields')
            data=[{k:r[k] for k in fields} for r in data]
        elif p['operation']=='split':
            if type(p.get('seed')) is not int or not 0<float(p.get('train_fraction',0))<1 or not p.get('group_field') or not p.get('split_field'):
                raise PreparationError('Split method, seed, group and allocation must be explicit')
            groups=sorted({str(r[p['group_field']]) for r in data})
            random.Random(p['seed']).shuffle(groups)
            train=set(groups[:int(len(groups)*p['train_fraction'])])
            data=[{**r,p['split_field']:('train' if str(r[p['group_field']]) in train else 'test')} for r in data]
        else: raise PreparationError('Transform operation is not allowlisted')
        content=json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2).encode()
        if len(content)>MAX_BYTES: raise PreparationError('Transformed artifact exceeds bound')
        return Artifact(content=content,parent_ids=[parent.resource_id],metadata={'transform':'declarative-v1',
            'parameters':p,'seed':p.get('seed'),'parent_checksums':{parent.resource_id:parent.checksum}})
