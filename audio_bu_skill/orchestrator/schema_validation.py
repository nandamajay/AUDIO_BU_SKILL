"""Shared JSON-Schema load/validate plumbing for skills/*/validator.py.

Each skill directory keeps its own schema.json + validator.py (the
laei-style skill package shape reviewed earlier); this module is just the
identical load-and-validate mechanics factored out so four validator.py
files don't reimplement the same jsonschema boilerplate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema


class SchemaValidationError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def load_schema(schema_path: str | Path) -> dict[str, Any]:
    return json.loads(Path(schema_path).read_text(encoding="utf-8"))


def validate_against(instance: dict[str, Any], schema: dict[str, Any], *, schema_key: str, error_code: str) -> None:
    sub_schema = schema.get(schema_key)
    if sub_schema is None:
        raise SchemaValidationError(code="SCHEMA_MISSING_SECTION", message=f"schema.json has no '{schema_key}' section",
                                     details={"schema_key": schema_key})
    try:
        jsonschema.validate(instance=instance, schema=sub_schema)
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(code=error_code, message=exc.message,
                                     details={"path": list(exc.absolute_path)}) from exc
