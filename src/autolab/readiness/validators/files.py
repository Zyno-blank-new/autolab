import json
from pathlib import Path
from autolab.preparation.handlers.base import MAX_BYTES, SAFE_SUFFIXES
from autolab.preparation.manifest import checksum


class FileValidator:
    def load(self, resource, evidence):
        path=Path(resource.path_or_uri)
        exists=path.is_file()
        evidence.add(resource,'file_exists',exists,'Artifact presence','resource')
        if not exists: return None
        valid=path.stat().st_size<=MAX_BYTES and path.suffix in SAFE_SUFFIXES
        evidence.add(resource,'safe_format',valid,'Bounded data format; executable formats unsupported')
        if not valid: return None
        evidence.add(resource,'sha256',checksum(path)==resource.checksum,'Exact artifact hash')
        try:
            text=path.read_text()
            data=json.loads(text) if path.suffix=='.json' else [json.loads(r) for r in text.splitlines()] if path.suffix=='.jsonl' else text
            evidence.add(resource,'readable',True,'Artifact parsed as data')
            return data
        except (OSError,ValueError,UnicodeError):
            evidence.add(resource,'readable',False,'Artifact unreadable or malformed')
            return None
