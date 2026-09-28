"""Normalize parser output and report how complete each extraction is."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from contextvault.core.models import DocumentSection, ParsedDocument
from contextvault.parsers.registry import ParserRegistry, create_default_registry


ExtractionStatus = Literal["ok", "empty", "unsupported", "truncated", "error"]


@dataclass(frozen=True)
class ExtractionResult:
    document: ParsedDocument | None
    status: ExtractionStatus
    parser: str | None
    parser_version: str | None
    word_count: int = 0
    bytes_read: int | None = None
    error: str | None = None

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "parser": self.parser,
            "parser_version": self.parser_version,
            "word_count": self.word_count,
            "bytes_read": self.bytes_read,
            "error": self.error,
        }


class DocumentExtractor:
    """Run one registered parser, normalize its document, and track limits.

    The default registry is created without a vision model. OCR remains an
    optional local parser capability; extraction and indexing never probe a
    generative provider.
    """

    def __init__(self, registry: ParserRegistry | None = None):
        self.registry = registry or create_default_registry(ocr_client=None)

    def extract(
        self, file_path: str | Path, file_id: str, extension: str | None = None
    ) -> ExtractionResult:
        path = Path(file_path)
        ext = (extension or path.suffix).lower()
        parser = self.registry.get_parser(ext)
        if parser is None:
            return ExtractionResult(
                document=None,
                status="unsupported",
                parser=None,
                parser_version=None,
                error=f"No extractor is registered for {ext or 'files without an extension'}.",
            )

        try:
            document = parser.parse(path, file_id)
            self._normalize_document(document, path)
            metadata = document.metadata
            truncated = bool(metadata.get("truncated") or metadata.get("incomplete"))
            has_text = bool(document.text.strip() or any(s.text.strip() for s in document.sections))
            if truncated:
                status: ExtractionStatus = "truncated"
            elif not has_text and metadata.get("source_type") == "image" and metadata.get("ocr_backend") == "none":
                status = "unsupported"
            elif has_text:
                status = "ok"
            else:
                status = "empty"

            bytes_read = metadata.get("bytes_read")
            if bytes_read is not None:
                try:
                    bytes_read = int(bytes_read)
                except (TypeError, ValueError):
                    bytes_read = None

            return ExtractionResult(
                document=document,
                status=status,
                parser=type(parser).__name__,
                parser_version=str(getattr(parser, "version", "1")),
                word_count=len(document.text.split()),
                bytes_read=bytes_read,
            )
        except Exception as exc:
            return ExtractionResult(
                document=None,
                status="error",
                parser=type(parser).__name__,
                parser_version=str(getattr(parser, "version", "1")),
                error=f"{type(exc).__name__}: {exc}",
            )

    @classmethod
    def _normalize_document(cls, document: ParsedDocument, path: Path) -> None:
        document.path = document.path or str(path)
        document.text = cls._normalize_text(document.text)
        document.title = cls._clean_string(document.title, 1000) if document.title else path.name
        document.metadata = cls._sanitize(document.metadata)
        normalized_sections: list[DocumentSection] = []
        for section in document.sections:
            section.text = cls._normalize_text(section.text)
            section.heading = cls._clean_string(section.heading, 1000) if section.heading else None
            section.metadata = cls._sanitize(section.metadata)
            normalized_sections.append(section)
        document.sections = normalized_sections

        if document.text and not document.sections:
            document.sections = [DocumentSection(
                heading="Main",
                text=document.text,
                line_start=1,
                line_end=max(1, document.text.count("\n") + 1),
                char_start=0,
                char_end=len(document.text),
                metadata={"heading": "Main"},
            )]

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        if value is None:
            return ""
        return str(value).replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _clean_string(value: Any, max_length: int) -> str:
        text = str(value).replace("\x00", "")
        return text[:max_length]

    @classmethod
    def _sanitize(cls, value: Any, depth: int = 0) -> Any:
        """Bound parser metadata and convert it to JSON-safe scalar values."""
        if depth > 8:
            return "[metadata depth limit]"
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Path):
            return cls._clean_string(value, 2000)
        if isinstance(value, str):
            return cls._clean_string(value, 4000)
        if isinstance(value, dict):
            items = list(value.items())[:200]
            return {
                cls._clean_string(key, 256): cls._sanitize(item, depth + 1)
                for key, item in items
            }
        if isinstance(value, (list, tuple, set)):
            return [cls._sanitize(item, depth + 1) for item in list(value)[:200]]
        return cls._clean_string(value, 1000)
