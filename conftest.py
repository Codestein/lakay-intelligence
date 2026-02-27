"""Repository-level pytest compatibility shims.

Allows tests to run in environments with Python < 3.11 and without optional
jsonschema installed.
"""

from __future__ import annotations

import datetime as _datetime
import enum as _enum
import sys
import types
from typing import Any

if not hasattr(_datetime, "UTC"):
    _datetime.UTC = _datetime.timezone.utc

if not hasattr(_enum, "StrEnum"):
    class StrEnum(str, _enum.Enum):
        pass

    _enum.StrEnum = StrEnum

try:
    import jsonschema as _jsonschema  # noqa: F401
except ModuleNotFoundError:
    fallback = types.ModuleType("jsonschema")

    class ValidationError(Exception):
        pass

    def _type_ok(value: Any, expected: str) -> bool:
        return {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }.get(expected, True)

    def _validate(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
        schema_type = schema.get("type")
        if isinstance(schema_type, str) and not _type_ok(instance, schema_type):
            raise ValidationError(f"{path} expected {schema_type}")
        if "const" in schema and instance != schema["const"]:
            raise ValidationError(f"{path} const mismatch")
        if "enum" in schema and instance not in schema["enum"]:
            raise ValidationError(f"{path} enum mismatch")
        if isinstance(instance, dict):
            for required in schema.get("required", []):
                if required not in instance:
                    raise ValidationError(f"{path}.{required} is required")
            for key, subschema in schema.get("properties", {}).items():
                if key in instance:
                    _validate(instance[key], subschema, f"{path}.{key}")
        if isinstance(instance, list) and "items" in schema:
            for idx, item in enumerate(instance):
                _validate(item, schema["items"], f"{path}[{idx}]")

    def validate(instance: Any, schema: dict[str, Any]) -> None:
        _validate(instance, schema)

    fallback.ValidationError = ValidationError
    fallback.validate = validate
    sys.modules["jsonschema"] = fallback
