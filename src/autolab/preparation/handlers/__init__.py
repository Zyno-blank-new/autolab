from .local import LocalHandler
from .synthetic import SyntheticHandler
from .transform import TransformHandler
from .download import DownloadHandler


def default_handlers():
    return {'local':LocalHandler(),'synthetic':SyntheticHandler(),'transform':TransformHandler(),'download':DownloadHandler()}
