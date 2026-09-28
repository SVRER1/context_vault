"""Stable request and result types for deterministic indexed retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from contextvault.query.ast import RuleNode


@dataclass(frozen=True)
class SearchRequest:
    vault_id: str
    query: str | None = None
    rule: RuleNode | None = None
    source_scope: str | None = None
    limit: int = 20
    passages_per_file: int = 3
    freshness_policy: Literal["reconcile", "cached"] = "reconcile"


@dataclass(frozen=True)
class PassageHit:
    chunk_id: str
    snippet: str
    score: float
    page: int | None = None
    slide: int | None = None
    section: str | None = None
    heading: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    sheet: str | None = None
    cell_range: str | None = None


@dataclass(frozen=True)
class SearchHit:
    file_id: str
    absolute_path: str
    relative_path: str
    filename: str
    extension: str
    mime_type: str | None
    size: int
    modified: float
    score: float
    matched_fields: tuple[str, ...]
    passages: tuple[PassageHit, ...]
    extract_status: str
    content_complete: bool


@dataclass(frozen=True)
class SearchResponse:
    hits: tuple[SearchHit, ...]
    unknown_ids: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    index_run_id: str | None = None
