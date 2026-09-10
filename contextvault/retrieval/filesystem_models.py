"""Explicit models for filesystem-native retrieval and evidence construction."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    vault_id: str
    source_scope: str | None = None
    operation: str = "ask"
    context_budget: int = 12000
    output_type: str = "answer"
    hints: tuple[str, ...] = ()
    max_rounds: int = 2
    max_candidates: int = 20
    max_deep_reads: int = 5
    max_bytes_per_read: int = 512_000


@dataclass(frozen=True)
class FileSurvey:
    relative_path: str
    filename: str
    directory: str
    extension: str
    size: int
    mtime: float
    parser: str | None
    mime_family: str
    preview: str = ""


@dataclass
class CandidateFile:
    survey: FileSurvey
    score: float
    reasons: list[str] = field(default_factory=list)
    relevant_preview: str = ""
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class EvidencePassage:
    evidence_id: str
    relative_path: str
    text: str
    reason: str
    heading: str | None = None
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    extraction_method: str = "filesystem"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceDocument:
    request_id: str
    query: str
    source_scope: str | None
    markdown: str
    passages: list[EvidencePassage]
    runtime_dir: str
    sufficient: bool
    insufficiency_reason: str | None = None

