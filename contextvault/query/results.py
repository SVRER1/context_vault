"""Immutable result contract shared by search and operation planning."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionResult:
    matched_ids: tuple[str, ...]
    unknown_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()
    index_run_id: str | None = None
