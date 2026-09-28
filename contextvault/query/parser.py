"""Small recursive-descent parser for deterministic vault selection rules."""

from __future__ import annotations

from dataclasses import dataclass

from contextvault.query.ast import All, Any, Not, Predicate, RuleNode
from contextvault.query.errors import QueryParseError, QueryValidationError
from contextvault.query.validation import validate

MAX_QUERY_LENGTH = 4096
MAX_NESTING = 32


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    column: int


def _tokenize(source: str) -> list[_Token]:
    if len(source) > MAX_QUERY_LENGTH:
        raise QueryParseError(f"Query exceeds {MAX_QUERY_LENGTH} characters", MAX_QUERY_LENGTH + 1)
    tokens: list[_Token] = []
    i = 0
    while i < len(source):
        char = source[i]
        if char.isspace():
            i += 1
            continue
        start = i
        if char == '"':
            i += 1
            value = []
            while i < len(source) and source[i] != '"':
                if source[i] == "\\":
                    i += 1
                    if i >= len(source):
                        raise QueryParseError("Unterminated escape in quoted value", start + 1)
                    escaped = source[i]
                    if escaped in {'"', "\\"}:
                        value.append(escaped)
                    elif escaped in {"n", "r", "t"}:
                        value.append({"n": "\n", "r": "\r", "t": "\t"}[escaped])
                    else:
                        value.extend(("\\", escaped))
                else:
                    value.append(source[i])
                i += 1
            if i >= len(source):
                raise QueryParseError("Unterminated quoted value", start + 1)
            i += 1
            tokens.append(_Token("PHRASE", "".join(value), start + 1))
            continue
        if char in "():~":
            kind = {"(": "LPAREN", ")": "RPAREN", ":": "COLON", "~": "TILDE"}[char]
            tokens.append(_Token(kind, char, start + 1))
            i += 1
            continue
        if char in "<>=!":
            i += 1
            if i < len(source) and source[i] == "=":
                i += 1
            op = source[start:i]
            if op not in {"=", "!=", ">", ">=", "<", "<="}:
                raise QueryParseError(f"Unsupported operator {op!r}", start + 1)
            tokens.append(_Token("OP", op, start + 1))
            continue
        while i < len(source) and not source[i].isspace() and source[i] not in '():~<>!="':
            i += 1
        if i == start:
            raise QueryParseError(f"Unexpected character {char!r}", start + 1)
        value = source[start:i]
        keyword = value.upper() if value.upper() in {"AND", "OR", "NOT"} else "WORD"
        tokens.append(_Token(keyword, value, start + 1))
    tokens.append(_Token("EOF", "", len(source) + 1))
    return tokens


class _Parser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = _tokenize(source)
        self.position = 0
        self.depth = 0
        self.unary_depth = 0

    @property
    def current(self) -> _Token:
        return self.tokens[self.position]

    def accept(self, kind: str) -> _Token | None:
        if self.current.kind == kind:
            token = self.current
            self.position += 1
            return token
        return None

    def require(self, kind: str, message: str) -> _Token:
        token = self.accept(kind)
        if token is None:
            raise QueryParseError(message, self.current.column)
        return token

    def parse(self) -> RuleNode:
        if self.current.kind == "EOF":
            raise QueryParseError("Query cannot be empty", 1)
        root = self.parse_or()
        if self.current.kind != "EOF":
            raise QueryParseError(f"Unexpected token {self.current.value!r}", self.current.column)
        return root

    def parse_or(self) -> RuleNode:
        children = [self.parse_and()]
        while self.accept("OR"):
            children.append(self.parse_and())
        return children[0] if len(children) == 1 else Any(tuple(children))

    def parse_and(self) -> RuleNode:
        children = [self.parse_unary()]
        while self.accept("AND"):
            children.append(self.parse_unary())
        return children[0] if len(children) == 1 else All(tuple(children))

    def parse_unary(self) -> RuleNode:
        if self.accept("NOT"):
            self.unary_depth += 1
            if self.unary_depth > MAX_NESTING:
                raise QueryParseError(f"Query nesting exceeds {MAX_NESTING} levels", self.current.column)
            child = self.parse_unary()
            self.unary_depth -= 1
            return Not(child)
        if self.accept("LPAREN"):
            self.depth += 1
            if self.depth > MAX_NESTING:
                raise QueryParseError(f"Query nesting exceeds {MAX_NESTING} levels", self.current.column)
            node = self.parse_or()
            self.require("RPAREN", "Expected ')' to close group")
            self.depth -= 1
            return node
        return self.parse_predicate()

    def parse_predicate(self) -> Predicate:
        field_token = self.require("WORD", "Expected a field predicate")
        field = field_token.value.casefold()
        operator = self.accept("COLON") or self.accept("OP") or self.accept("TILDE")
        if operator is None:
            raise QueryParseError("Expected ':', a comparison operator, or '~' after field", self.current.column)
        value_token = self.current
        if value_token.kind not in {"WORD", "PHRASE"}:
            raise QueryParseError("Expected a value after field operator", value_token.column)
        self.position += 1

        if operator.kind == "COLON":
            if field == "content":
                op = "phrase" if value_token.kind == "PHRASE" else "contains"
            elif field in {"extension", "type", "mime", "tag", "hash"}:
                op = "eq"
            else:
                op = "contains"
        elif operator.kind == "TILDE":
            op = "regex"
            if value_token.kind != "PHRASE":
                raise QueryParseError("Regex patterns must be quoted", value_token.column)
        else:
            op = operator.value
        try:
            return validate(Predicate(field, op, value_token.value))
        except QueryValidationError as exc:
            if (
                "ISO-8601" in exc.message or "Size must" in exc.message
                or exc.message.startswith("Invalid regex")
                or "Regex exceeds" in exc.message
                or "repetition is not supported" in exc.message
                or "backreferences" in exc.message
            ):
                column = value_token.column
            elif "Operator" in exc.message:
                column = operator.column
            else:
                column = field_token.column
            raise QueryValidationError(exc.message, column) from exc


def parse_query(source: str) -> RuleNode:
    """Parse and canonicalize a structured query expression."""
    return _Parser(source).parse()
