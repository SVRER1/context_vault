"""Location-aware query parsing and validation errors."""


class QueryError(ValueError):
    def __init__(self, message: str, column: int | None = None):
        self.message = message
        self.column = column
        suffix = f" at column {column}" if column is not None else ""
        super().__init__(f"{message}{suffix}")

    def render(self, source: str) -> str:
        if self.column is None:
            return self.message
        return f"{source}\n{' ' * max(0, self.column - 1)}^\n{self.message} (column {self.column})"


class QueryParseError(QueryError):
    """Malformed structured query expression."""


class QueryValidationError(QueryError):
    """Well-formed query with an unsupported or mistyped predicate."""
