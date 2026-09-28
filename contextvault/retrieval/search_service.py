"""FTS5/BM25 search over the canonical incremental index.

Unquoted input is tokenized and terms are ORed; a whole query wrapped in
double quotes is an exact phrase. BM25 uses filename/text/heading/section
weights 2/5/3/1. The exposed higher-is-better score is ``max(0, -bm25)`` plus
0.20 for a filename match and 0.10 for a heading match. Ties use normalized
path then stable file ID. No stemming, query expansion, or model ranking runs.
"""

from __future__ import annotations

import re

from contextvault.core.config import AppConfig, get_config
from contextvault.core.vault import Vault
from contextvault.query.ast import All, Any, Not, Predicate, RuleNode
from contextvault.query.executor import RuleExecutor
from contextvault.retrieval.search_models import PassageHit, SearchHit, SearchRequest, SearchResponse
from contextvault.storage.database import Database


class SearchService:
    """Rank located passages deterministically; never invokes a model."""

    BM25_WEIGHTS = "0, 0, 0, 0, 2.0, 5.0, 3.0, 1.0"
    FILENAME_BOOST = 0.20
    HEADING_BOOST = 0.10

    def __init__(self, vault: Vault, db: Database, config: AppConfig | None = None, rule_executor: RuleExecutor | None = None):
        self.vault = vault
        self.db = db
        self.config = config or get_config()
        self.rule_executor = rule_executor or RuleExecutor(vault, db, self.config)

    def search(self, request: SearchRequest) -> SearchResponse:
        if request.vault_id != self.vault.vault_id:
            raise ValueError("Search request vault does not match the active vault.")
        if not 1 <= request.limit <= 1000:
            raise ValueError("Search limit must be between 1 and 1000.")
        if not 1 <= request.passages_per_file <= 20:
            raise ValueError("passages_per_file must be between 1 and 20.")
        if request.freshness_policy not in {"reconcile", "cached"}:
            raise ValueError("freshness_policy must be 'reconcile' or 'cached'.")
        if not request.query and request.rule is None:
            raise ValueError("Search requires free text, a rule AST, or both.")

        reconcile = request.freshness_policy == "reconcile"
        snapshot = self.rule_executor.prepare_universe(
            scope=request.source_scope,
            reconcile=reconcile,
        )
        if snapshot.index_status == "failed":
            return SearchResponse(
                hits=(),
                unknown_ids=RuleExecutor._ordered(snapshot.file_ids, snapshot.rows_by_id),
                diagnostics=snapshot.diagnostics,
                index_run_id=snapshot.index_run_id,
            )
        selection = None
        if request.rule is not None:
            selection = self.rule_executor.evaluate_prepared(request.rule, snapshot)
            allowed_ids = set(selection.matched_ids)
        else:
            allowed_ids = set(snapshot.file_ids)

        lexical_query = request.query.strip() if request.query else self._positive_query(request.rule)
        terms, phrase, expression = self._compile_text_query(lexical_query)
        passages_by_file: dict[str, list[dict]] = {}
        unranked_ids: set[str] = set()
        if expression and allowed_ids:
            passages_by_file, unranked_ids = self._ranked_passages(
                expression,
                sorted(allowed_ids),
                request.passages_per_file,
            )

        rows_by_id = snapshot.rows_by_id
        hits = []
        incomplete_without_hit = set()
        for file_id in allowed_ids:
            row = rows_by_id[file_id]
            passage_rows = passages_by_file.get(file_id, [])
            filename_match = bool(terms and self._field_matches(row["filename"], terms, phrase))
            if lexical_query and not passage_rows and not filename_match:
                if row.get("extract_status") not in {"ok", "empty"}:
                    incomplete_without_hit.add(file_id)
                continue
            heading_match = any(
                terms and self._field_matches(passage.get("heading") or "", terms, phrase)
                for passage in passage_rows
            )
            text_match = any(
                terms and self._field_matches(passage.get("text") or "", terms, phrase)
                for passage in passage_rows
            )
            matched_fields = tuple(
                field for field, matched in (
                    ("filename", filename_match), ("heading", heading_match), ("content", text_match)
                ) if matched
            )
            passages = tuple(
                PassageHit(
                    chunk_id=item["id"],
                    snippet=self._snippet(item["text"], terms, phrase),
                    score=max(0.0, -float(item["bm25_score"])),
                    page=item.get("page"),
                    slide=item.get("slide"),
                    section=item.get("section"),
                    heading=item.get("heading"),
                    line_start=item.get("line_start"),
                    line_end=item.get("line_end"),
                    sheet=item.get("sheet"),
                    cell_range=item.get("cell_range"),
                )
                for item in passage_rows
            )
            base = max((passage.score for passage in passages), default=0.0)
            score = base + (self.FILENAME_BOOST if filename_match else 0.0) + (
                self.HEADING_BOOST if heading_match else 0.0
            )
            hits.append(SearchHit(
                file_id=file_id,
                absolute_path=str(self.vault.root_path / row["relative_path"]),
                relative_path=row["relative_path"],
                filename=row["filename"],
                extension=row["extension"],
                mime_type=row.get("mime_type"),
                size=int(row["size"]),
                modified=float(row["mtime"]),
                score=score,
                matched_fields=matched_fields,
                passages=passages,
                extract_status=row.get("extract_status") or "pending",
                content_complete=row.get("extract_status") in {"ok", "empty"},
            ))

        hits.sort(key=lambda hit: (-hit.score, rows_by_id[hit.file_id]["path_key"], hit.file_id))
        diagnostics = list(snapshot.diagnostics)
        unknown_ids = set(selection.unknown_ids) if selection is not None else set()
        unknown_ids.update(incomplete_without_hit)
        unknown_ids.update(unranked_ids)
        if selection is not None:
            diagnostics.extend(selection.diagnostics)
        if incomplete_without_hit:
            diagnostics.append("Some files have incomplete extraction and may contain additional matches.")
        if unranked_ids:
            diagnostics.append("The passage ranking row limit was reached; some matching files are unknown.")
        return SearchResponse(
            hits=tuple(hits[:request.limit]),
            unknown_ids=RuleExecutor._ordered(unknown_ids, rows_by_id),
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            index_run_id=snapshot.index_run_id,
        )

    def _ranked_passages(self, expression: str, file_ids: list[str], passages_per_file: int):
        by_file: dict[str, list[dict]] = {}
        unranked: set[str] = set()
        row_limit = 50_000
        for offset in range(0, len(file_ids), 400):
            batch = file_ids[offset:offset + 400]
            placeholders = ",".join("?" for _ in batch)
            matched = self.db.fetch_all(
                f"SELECT DISTINCT file_id FROM chunks_fts WHERE chunks_fts MATCH ? "
                f"AND vault_id=? AND file_id IN ({placeholders})",
                (expression, self.vault.vault_id, *batch),
            )
            matched_ids = {row["file_id"] for row in matched}
            sql = f"""SELECT c.id, c.file_id, c.relative_path, c.chunk_index, c.text,
                       c.page, c.section, c.heading, c.line_start, c.line_end,
                       c.slide, c.sheet, c.cell_range,
                       bm25(chunks_fts, {self.BM25_WEIGHTS}) AS bm25_score
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.id
                WHERE chunks_fts MATCH ? AND chunks_fts.vault_id = ?
                  AND chunks_fts.file_id IN ({placeholders})
                ORDER BY bm25_score ASC, c.file_id, c.chunk_index
                LIMIT ?"""
            rows = self.db.fetch_all(sql, (expression, self.vault.vault_id, *batch, row_limit + 1))
            if len(rows) > row_limit:
                rows = rows[:row_limit]
                ranked_in_batch = {row["file_id"] for row in rows}
                unranked.update(matched_ids - ranked_in_batch)
            for row in rows:
                passages = by_file.setdefault(row["file_id"], [])
                if len(passages) < passages_per_file:
                    passages.append(row)
        return by_file, unranked

    @classmethod
    def _compile_text_query(cls, query: str | None):
        if not query:
            return [], False, None
        source = query.strip()
        phrase = len(source) >= 2 and source[0] == source[-1] == '"'
        if phrase:
            phrase_text = source[1:-1].replace("\\\"", "\"").replace("\\\\", "\\")
            terms = re.findall(r"[\w]+", phrase_text, flags=re.UNICODE)
            if not terms:
                return [], True, None
            return terms, True, f'text : "{cls._fts_quote(phrase_text)}"'

        terms = re.findall(r"[\w]+", source, flags=re.UNICODE)
        if not terms:
            return [], False, None
        alternatives = " OR ".join(f'"{cls._fts_quote(term)}"' for term in terms)
        return terms, False, f"({alternatives})"

    @classmethod
    def _positive_query(cls, node: RuleNode | None) -> str | None:
        if node is None:
            return None
        found: list[str] = []

        def visit(current, negated=False):
            if isinstance(current, Not):
                visit(current.child, not negated)
            elif isinstance(current, Predicate) and current.field == "content" and not negated:
                value = str(current.value)
                found.append(f'"{value}"' if current.op == "phrase" else value)
            elif isinstance(current, (All, Any)):
                for child in current.children:
                    visit(child, negated)

        visit(node)
        return " OR ".join(found) if found else None

    @staticmethod
    def _fts_quote(value: str) -> str:
        return value.replace('"', '""')

    @staticmethod
    def _field_matches(value: str, terms: list[str], phrase: bool) -> bool:
        normalized = value.casefold()
        if phrase:
            value_tokens = " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))
            return " ".join(terms).casefold() in value_tokens
        return any(term.casefold() in normalized for term in terms)

    @classmethod
    def _snippet(cls, text: str, terms: list[str], phrase: bool, radius: int = 110) -> str:
        if not text:
            return ""
        lowered = text.casefold()
        needles = terms
        matches = [lowered.find(needle.casefold()) for needle in needles if needle and lowered.find(needle.casefold()) >= 0]
        if not matches:
            start, end = 0, min(len(text), radius * 2)
        else:
            position = min(matches)
            start = max(0, position - radius)
            end = min(len(text), position + radius)
        snippet = text[start:end].strip()
        return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")
