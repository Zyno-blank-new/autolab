from .base import Artifact, require_keys, safe_path
from autolab.preparation.models import PreparationError


class LocalHandler:
    def prepare(self, requirement, context):
        require_keys(requirement.parameters, {'path'}, {'path'})
        path=safe_path(requirement.parameters['path'],context['allowed_roots'])
        if str(path) not in context.get('allowed_local_paths',set()):
            raise PreparationError('Existing resource path lacks an operator-supplied catalog binding')
        return Artifact(existing_path=path,metadata={'acquisition':'existing reference; no redundant copy'})
