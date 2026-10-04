"""Lossless Pydantic JSON storage; reject invalid nested JSON before SQLite."""
import json
from typing import TypeVar
from autolab.schemas import Record

T = TypeVar("T", bound=Record)


def serialize(record: Record) -> str:
    # model_copy and nested container mutations can bypass validation; validate
    # again at the persistence boundary, and never silently replace NaN by null.
    data = record.model_dump(mode="python")
    validated = type(record).model_validate(data)
    return json.dumps(validated.model_dump(mode="json"), allow_nan=False, sort_keys=True)


def deserialize(model: type[T], payload: str) -> T:
    return model.model_validate_json(payload)
