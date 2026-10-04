"""Data-only handler interface; no shell, eval, installs or remote dataset code."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from autolab.preparation.models import PreparationError

MAX_BYTES=1_000_000
SAFE_SUFFIXES={'.json','.jsonl','.txt','.csv'}


@dataclass
class Artifact:
    content: bytes | None = None
    existing_path: Path | None = None
    parent_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class Handler(Protocol):
    def prepare(self, requirement, context) -> Artifact: ...


def require_keys(parameters, allowed, required=()):
    if set(parameters)-set(allowed) or set(required)-set(parameters):
        raise PreparationError('Handler parameters do not match the allowlisted data contract')


def safe_path(path, roots):
    path=Path(path).resolve()
    if not any(path.is_relative_to(Path(root).resolve()) for root in roots):
        raise PreparationError('Resource path is outside explicitly allowed data roots')
    if path.suffix.lower() not in SAFE_SUFFIXES or not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise PreparationError('Missing, oversized or unsupported resource data file')
    return path
