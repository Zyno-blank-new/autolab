"""Bounded declarative structured/text generation; model-produced data is untrusted."""
import json
import random
from autolab.preparation.models import PreparationError
from .base import Artifact, MAX_BYTES, require_keys


class SyntheticHandler:
    def prepare(self, requirement, context):
        p=requirement.parameters
        require_keys(p, {'data','seed','shuffle','specification','license'}, {'data','specification'})
        if p.get('seed') is not None and type(p['seed']) is not int:
            raise PreparationError('Synthetic seed must be an integer when provided')
        data=p['data']
        if not isinstance(data,(dict,list,str)) or (isinstance(data,list) and len(data)>2000):
            raise PreparationError('Synthetic artifact must be bounded JSON/text data')
        if p.get('shuffle'):
            if not isinstance(data,list) or type(p.get('seed')) is not int:
                raise PreparationError('Reproducible shuffle requires a list and explicit integer seed')
            data=list(data); random.Random(p['seed']).shuffle(data)
        content=json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2).encode()
        if len(content)>MAX_BYTES: raise PreparationError('Synthetic artifact exceeds byte bound')
        return Artifact(content=content,metadata={'generator':'declarative-json-v1',
            'seed':p.get('seed'),'seed_scope':'Local data ordering only; model proposal generation is not seed-controlled','specification':p['specification'], 'license':p.get('license'),
            'generation_parameters':p,'intended_role':requirement.purpose,
            'note':'Generation success is not scientific validity; independent audit required'})
