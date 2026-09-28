"""Immutable selection-rule AST and versioned JSON representation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from contextvault.query.errors import QueryValidationError

AST_VERSION = 1


@dataclass(frozen=True)
class All:
    children: tuple["RuleNode", ...]

    def __post_init__(self):
        object.__setattr__(self, "children", tuple(self.children))


@dataclass(frozen=True)
class Any:
    children: tuple["RuleNode", ...]

    def __post_init__(self):
        object.__setattr__(self, "children", tuple(self.children))


@dataclass(frozen=True)
class Not:
    child: "RuleNode"


@dataclass(frozen=True)
class Predicate:
    field: str
    op: str
    value: str | int | bool


RuleNode: TypeAlias = All | Any | Not | Predicate


def _to_data(node: RuleNode) -> dict:
    if isinstance(node, (All, Any)):
        if not node.children:
            raise QueryValidationError("Boolean groups cannot be empty")
        return {
            "kind": "all" if isinstance(node, All) else "any",
            "children": [_to_data(child) for child in node.children],
        }
    if isinstance(node, Not):
        return {"kind": "not", "child": _to_data(node.child)}
    if isinstance(node, Predicate):
        return {"kind": "predicate", "field": node.field, "op": node.op, "value": node.value}
    raise QueryValidationError(f"Unsupported AST node: {type(node).__name__}")


def serialize(node: RuleNode) -> dict:
    """Return a JSON-safe, versioned AST object."""
    return {"version": AST_VERSION, "root": _to_data(node)}


def _from_data(data: dict, depth: int = 0) -> RuleNode:
    if depth > 64:
        raise QueryValidationError("AST nesting exceeds 64 levels")
    if not isinstance(data, dict):
        raise QueryValidationError("AST node must be an object")
    kind = data.get("kind")
    if kind in {"all", "any"}:
        children = data.get("children")
        if not isinstance(children, list) or not children:
            raise QueryValidationError("Boolean groups require at least one child")
        nodes = tuple(_from_data(child, depth + 1) for child in children)
        return All(nodes) if kind == "all" else Any(nodes)
    if kind == "not":
        if "child" not in data:
            raise QueryValidationError("NOT node requires a child")
        return Not(_from_data(data["child"], depth + 1))
    if kind == "predicate":
        field, op, value = data.get("field"), data.get("op"), data.get("value")
        if not isinstance(field, str) or not isinstance(op, str) or not isinstance(value, (str, int, bool)):
            raise QueryValidationError("Predicate requires string field/operator and scalar value")
        return Predicate(field, op, value)
    raise QueryValidationError(f"Unknown AST node kind: {kind!r}")


def deserialize(data: dict) -> RuleNode:
    """Load a versioned AST; callers validate fields before execution."""
    if not isinstance(data, dict) or data.get("version") != AST_VERSION:
        raise QueryValidationError(f"Unsupported AST version; expected {AST_VERSION}")
    if "root" not in data:
        raise QueryValidationError("Versioned AST requires a root node")
    return _from_data(data["root"])


def all_of(*children: RuleNode) -> All:
    return All(tuple(children))


def any_of(*children: RuleNode) -> Any:
    return Any(tuple(children))


def negate(child: RuleNode) -> Not:
    return Not(child)


def predicate(field: str, op: str, value: str | int | bool) -> Predicate:
    """Builder API for GUI controls; intentionally does not parse strings."""
    return Predicate(field, op, value)


def any_content(*terms: str) -> Any:
    return Any(tuple(Predicate("content", "contains", term) for term in terms))


def all_content(*terms: str) -> All:
    return All(tuple(Predicate("content", "contains", term) for term in terms))
