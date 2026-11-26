"""Strict local candidate contracts; NOT the canonical OpenRGD validator."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

MAX_BYTES = 65536
MAX_DEPTH = 24
SCHEMA = json.loads((Path(__file__).parent / "schemas/cog-v0.1.schema.json").read_text())
Draft202012Validator.check_schema(SCHEMA)
FORMATS = FormatChecker()


class ContractError(ValueError):
    """Stable code only: never include private input in error messages."""


@FORMATS.checks("date-time", raises=(ValueError, TypeError))
def _date_time(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        return False
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.tzinfo is not None


VALIDATORS = {
    name: Draft202012Validator(
        {"$schema": SCHEMA["$schema"], "$defs": SCHEMA["$defs"], "$ref": "#/$defs/" + name},
        format_checker=FORMATS,
    )
    for name in SCHEMA["$defs"]
}


def encode(value: Any) -> bytes:
    """Bounded local serialization, not JCS or OPENRGD_SOURCE_TREE_SHA256_V1."""
    stack = [(value, 0)]
    visited = 0
    while stack:
        item, depth = stack.pop()
        visited += 1
        if depth > MAX_DEPTH or visited > 8192:
            raise ContractError("STRUCTURE_LIMIT")
        if isinstance(item, dict):
            if len(item) > 256 or not all(isinstance(key, str) for key in item):
                raise ContractError("INVALID_OBJECT")
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, (list, tuple)):
            if len(item) > 4096:
                raise ContractError("STRUCTURE_LIMIT")
            stack.extend((v, depth + 1) for v in item)
        elif isinstance(item, str) and len(item) > MAX_BYTES:
            raise ContractError("BYTE_LIMIT")
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise ContractError("INVALID_JSON") from None
    if len(raw) > MAX_BYTES:
        raise ContractError("BYTE_LIMIT")
    return raw


def decode(raw: str | bytes) -> dict:
    if not isinstance(raw, (str, bytes)):
        raise ContractError("INVALID_JSON")
    try:
        length = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
    except UnicodeError:
        raise ContractError("INVALID_JSON") from None
    if length > MAX_BYTES:
        raise ContractError("BYTE_LIMIT")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("DUPLICATE_KEY")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ContractError("NONFINITE_NUMBER")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, RecursionError, UnicodeError):
        raise ContractError("INVALID_JSON") from None
    if not isinstance(value, dict):
        raise ContractError("OBJECT_REQUIRED")
    encode(value)
    return value


def validate(name: str, value: dict) -> dict:
    if name not in VALIDATORS:
        raise ContractError("UNKNOWN_CONTRACT")
    encode(value)
    if next(VALIDATORS[name].iter_errors(value), None) is not None:
        raise ContractError("SCHEMA_VIOLATION:" + name)
    return value


def local_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(encode(value)).hexdigest()
