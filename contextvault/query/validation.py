"""Canonicalize and type-check query AST predicates."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone

from contextvault.query.ast import All, Any, Not, Predicate, RuleNode
from contextvault.query.errors import QueryValidationError

MAX_REGEX_LENGTH = 256
_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb|kib|mib|gib|tib)?\s*$", re.I)
_SIZE_FACTORS = {
    "b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4,
    "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4,
}
_COMPARATORS = {"=": "eq", "!=": "ne", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}
_TEXT_FIELDS = {"name", "path", "content"}
_ENUM_FIELDS = {"extension", "mime", "tag", "hash"}
_DATE_FIELDS = {"modified", "created"}


def parse_size(value: str) -> int:
    match = _SIZE.fullmatch(value)
    if not match:
        raise QueryValidationError("Size must be a number with optional B, KB, MB, GB, or TB unit")
    amount = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    return int(amount * _SIZE_FACTORS[unit])


def parse_timestamp(value: str) -> str:
    try:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.combine(date.fromisoformat(value), time.min)
    except ValueError as exc:
        raise QueryValidationError("Date must be an ISO-8601 date or timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def validate(node: RuleNode) -> RuleNode:
    """Return a canonical AST or raise a validation error."""
    if isinstance(node, All):
        if not node.children:
            raise QueryValidationError("AND groups cannot be empty")
        return All(tuple(validate(child) for child in node.children))
    if isinstance(node, Any):
        if not node.children:
            raise QueryValidationError("OR groups cannot be empty")
        return Any(tuple(validate(child) for child in node.children))
    if isinstance(node, Not):
        return Not(validate(node.child))
    if not isinstance(node, Predicate):
        raise QueryValidationError(f"Unsupported query node {type(node).__name__}")

    field = node.field.casefold()
    if field == "type":
        field = "extension"
    if field not in _TEXT_FIELDS | _ENUM_FIELDS | _DATE_FIELDS | {"size"}:
        raise QueryValidationError(f"Unknown field {node.field!r}")
    op = node.op.casefold()
    if op in _COMPARATORS:
        op = _COMPARATORS[op]
    value = node.value

    if field in {"name", "path"}:
        if op not in {"contains", "eq", "ne", "regex"}:
            raise QueryValidationError(f"Operator {op!r} is not supported for {field}")
        if op == "regex":
            pattern = str(value)
            if len(pattern) > MAX_REGEX_LENGTH:
                raise QueryValidationError(f"Regex exceeds {MAX_REGEX_LENGTH} characters")
            if re.search(r"\\[1-9]|\(\?[=!<:]", pattern):
                raise QueryValidationError("Regex backreferences and lookarounds are not supported")
            if re.search(r"\([^)]*[+*][^)]*\)[+*{]", pattern):
                raise QueryValidationError("Nested repetition is not supported in regex patterns")
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise QueryValidationError(f"Invalid regex: {exc}") from exc
            value = pattern
        else:
            value = str(value).casefold()
    elif field == "content":
        if op not in {"contains", "phrase"}:
            raise QueryValidationError(f"Operator {op!r} is not supported for content")
        value = str(value).casefold()
        if not value.strip():
            raise QueryValidationError("Content terms cannot be empty")
    elif field in _ENUM_FIELDS:
        allowed_ops = {"eq", "ne", "contains"} if field == "tag" else {"eq", "ne"}
        if op not in allowed_ops:
            raise QueryValidationError(f"Operator {op!r} is not supported for {field}")
        value = str(value).casefold()
        if field == "extension":
            value = value if value.startswith(".") else f".{value}"
    elif field == "size":
        if op not in {"eq", "ne", "gt", "gte", "lt", "lte"}:
            raise QueryValidationError(f"Operator {op!r} is not supported for size")
        value = value if isinstance(value, int) and not isinstance(value, bool) else parse_size(str(value))
        if value < 0:
            raise QueryValidationError("Size cannot be negative")
    elif field in _DATE_FIELDS:
        if op not in {"eq", "ne", "gt", "gte", "lt", "lte"}:
            raise QueryValidationError(f"Operator {op!r} is not supported for {field}")
        value = parse_timestamp(str(value))

    return Predicate(field, op, value)
