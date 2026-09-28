"""Parameterized predicate planning against the local SQLite index."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from contextvault.query.ast import Predicate
from contextvault.storage.database import Database


@dataclass(frozen=True)
class PredicateTruth:
    true_ids: frozenset[str]
    unknown_ids: frozenset[str] = frozenset()


class QueryPlanner:
    """Resolve one validated leaf predicate to matched and unknown file IDs."""

    def __init__(self, db: Database, vault_id: str, *, candidate_limit: int = 20_000):
        self.db = db
        self.vault_id = vault_id
        self.candidate_limit = candidate_limit
        self.diagnostics: list[str] = []

    def evaluate(self, predicate: Predicate, universe: frozenset[str], rows_by_id: dict[str, dict]) -> PredicateTruth:
        field, op, value = predicate.field, predicate.op, predicate.value
        if field == "content":
            return self._content(str(value), phrase=op == "phrase", universe=universe, rows_by_id=rows_by_id)
        if field in {"name", "path"} and op == "regex":
            ordered = sorted(universe, key=lambda file_id: (rows_by_id[file_id]["path_key"], file_id))
            candidates = ordered[: self.candidate_limit]
            if len(ordered) > len(candidates):
                self.diagnostics.append(
                    f"Regex candidate limit ({self.candidate_limit}) reached; remaining files are unknown."
                )
            pattern = re.compile(str(value), re.IGNORECASE)
            matched = set()
            for file_id in candidates:
                row = rows_by_id[file_id]
                target = row["filename"] if field == "name" else row["relative_path"]
                if pattern.search(target):
                    matched.add(file_id)
            unknown = set(ordered[len(candidates):])
            return PredicateTruth(frozenset(matched), frozenset(unknown))

        if field in {"name", "path"}:
            matched = set()
            for file_id in universe:
                target = rows_by_id[file_id]["filename" if field == "name" else "relative_path"].casefold()
                if (op == "contains" and str(value) in target) or (op == "eq" and target == value) or (op == "ne" and target != value):
                    matched.add(file_id)
            return PredicateTruth(frozenset(matched))

        sql, params = self._metadata_sql(predicate)
        rows = self.db.fetch_all(sql, params)
        return PredicateTruth(frozenset(row["id"] for row in rows if row["id"] in universe))

    def _metadata_sql(self, predicate: Predicate) -> tuple[str, tuple]:
        field, op, value = predicate.field, predicate.op, predicate.value
        comparator = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}.get(op)
        if field == "extension":
            sql_op = "!=" if op == "ne" else "="
            return f"SELECT id FROM files WHERE vault_id=? AND lower(extension) {sql_op} ?", (self.vault_id, value)
        if field == "mime":
            sql_op = "!=" if op == "ne" else "="
            return f"SELECT id FROM files WHERE vault_id=? AND lower(COALESCE(mime_type,'')) {sql_op} ?", (self.vault_id, value)
        if field == "size":
            return f"SELECT id FROM files WHERE vault_id=? AND size {comparator} ?", (self.vault_id, value)
        if field in {"modified", "created"}:
            column = "mtime" if field == "modified" else "created_time"
            timestamp = datetime.fromisoformat(str(value)).timestamp()
            return f"SELECT id FROM files WHERE vault_id=? AND {column} {comparator} ?", (self.vault_id, timestamp)
        if field == "hash":
            sql_op = "!=" if op == "ne" else "="
            return f"SELECT id FROM files WHERE vault_id=? AND lower(sha256) {sql_op} ?", (self.vault_id, value)
        if field == "tag":
            if op == "contains":
                return (
                    "SELECT file_id AS id FROM file_tags WHERE instr(tag_key,?)>0 AND file_id IN "
                    "(SELECT id FROM files WHERE vault_id=?)",
                    (value, self.vault_id),
                )
            sql_op = "!=" if op == "ne" else "="
            return (
                f"SELECT file_id AS id FROM file_tags WHERE tag_key {sql_op} ? AND file_id IN "
                "(SELECT id FROM files WHERE vault_id=?)",
                (value, self.vault_id),
            )
        raise ValueError(f"Planner received unsupported predicate: {field}/{op}")

    def _content(self, value: str, *, phrase: bool, universe: frozenset[str], rows_by_id: dict[str, dict]) -> PredicateTruth:
        terms = [value] if phrase else re.findall(r"[\w]+", value, flags=re.UNICODE)
        terms = [term for term in terms if term]
        matches: set[str] = set()
        if terms:
            if phrase:
                expression = f'text : "{self._fts_quote(terms[0])}"'
                rows = self.db.fetch_all(
                    "SELECT DISTINCT file_id FROM chunks_fts WHERE chunks_fts MATCH ? AND vault_id=?",
                    (expression, self.vault_id),
                )
                matches = {row["file_id"] for row in rows if row["file_id"] in universe}
            else:
                for term in terms:
                    expression = f'text : "{self._fts_quote(term)}"'
                    rows = self.db.fetch_all(
                        "SELECT DISTINCT file_id FROM chunks_fts WHERE chunks_fts MATCH ? AND vault_id=?",
                        (expression, self.vault_id),
                    )
                    term_ids = {row["file_id"] for row in rows if row["file_id"] in universe}
                    matches = term_ids if not matches and term == terms[0] else matches & term_ids

        incomplete = {
            file_id for file_id in universe
            if rows_by_id[file_id].get("extract_status") not in {"ok", "empty"}
        }
        
        
        unknown = incomplete - matches
        return PredicateTruth(frozenset(matches), frozenset(unknown))

    @staticmethod
    def _fts_quote(term: str) -> str:
        return term.replace('"', '""')
