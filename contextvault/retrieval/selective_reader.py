"""Scope-safe progressive reading of selected candidate files."""

import re
import uuid
from pathlib import Path

from contextvault.core.vault import Vault
from contextvault.parsers.registry import create_default_registry
from contextvault.retrieval.candidate_discovery import TEXT_EXTENSIONS
from contextvault.retrieval.filesystem_models import CandidateFile, EvidencePassage, RetrievalRequest
from contextvault.retrieval.filesystem_policy import validate_source_scope


class SelectiveReader:
    """Read only selected, in-scope passages with source locations."""

    def __init__(self, vault: Vault, ocr_client=None):
        self.vault = vault
        self.registry = create_default_registry(ocr_client=ocr_client)

    def read(self, candidate: CandidateFile, request: RetrievalRequest) -> list[EvidencePassage]:
        validate_source_scope(self.vault, request.source_scope)
        relative_path = candidate.survey.relative_path.replace("\\", "/")
        if not self.vault.is_in_scope(relative_path, request.source_scope):
            raise ValueError(f"Candidate is outside the selected scope: {relative_path}")
        path = self.vault.absolute_path(relative_path)
        if not path.is_file():
            return []

        if path.suffix.lower() in TEXT_EXTENSIONS:
            return self._read_text(path, relative_path, request)
        return self._read_structured(path, relative_path, candidate, request)

    def _read_text(self, path: Path, relative_path: str, request: RetrievalRequest) -> list[EvidencePassage]:
        terms = self._terms(request.query)
        try:
            if path.stat().st_size > request.max_bytes_per_read:
                return self._read_sampled_text(path, relative_path, terms, request.max_bytes_per_read)
        except OSError:
            return []
        passages: list[EvidencePassage] = []
        selected_lines: set[int] = set()
        total_bytes = 0
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                lines = []
                for line_number, line in enumerate(handle, start=1):
                    if total_bytes >= request.max_bytes_per_read:
                        break
                    total_bytes += len(line.encode("utf-8", errors="ignore"))
                    lines.append((line_number, line.rstrip("\n")))
        except OSError:
            return []

        matching = [
            index for index, (_, line) in enumerate(lines)
            if any(term in line.lower() for term in terms)
        ]
        if matching:
            for index in matching[:12]:
                selected_lines.update(range(max(0, index - 2), min(len(lines), index + 3)))
        else:
            selected_lines.update(range(min(len(lines), 60)))

        if not selected_lines:
            return []
        groups = self._contiguous_groups(sorted(selected_lines))
        for start_index, end_index in groups:
            text = "\n".join(lines[index][1] for index in range(start_index, end_index + 1)).strip()
            if not text:
                continue
            heading = self._heading_for(lines, start_index)
            passages.append(EvidencePassage(
                evidence_id=f"ev-{uuid.uuid4().hex[:10]}",
                relative_path=relative_path,
                text=text,
                reason="Lexical match with a bounded line window" if matching else "Candidate path/metadata match with bounded preview",
                heading=heading,
                line_start=lines[start_index][0],
                line_end=lines[end_index][0],
                extraction_method="line-window",
            ))
        return passages

    def _read_sampled_text(self, path: Path, relative_path: str, terms: list[str], max_bytes: int) -> list[EvidencePassage]:
        """Search bounded windows in a large file without sending it wholesale."""
        window_size = max(1024, max_bytes // 4)
        file_size = path.stat().st_size
        starts = {0, max(0, file_size - window_size), file_size // 3, (file_size * 2) // 3}
        matches: list[str] = []
        ranges: list[tuple[int, int]] = []
        with path.open("rb") as handle:
            for start in sorted(starts):
                handle.seek(start)
                raw = handle.read(window_size)
                text = raw.decode("utf-8", errors="ignore")
                lines = text.splitlines()
                selected = [
                    line for index, line in enumerate(lines)
                    if any(term in line.lower() for term in terms)
                    for line in lines[max(0, index - 1): min(len(lines), index + 2)]
                ]
                if selected:
                    matches.extend(selected)
                    ranges.append((start, start + len(raw)))
        if not matches:
            return []
        text = "\n".join(dict.fromkeys(matches))[:max_bytes]
        return [EvidencePassage(
            evidence_id=f"ev-{uuid.uuid4().hex[:10]}",
            relative_path=relative_path,
            text=text,
            reason="Lexical match in bounded sampled windows of a large file",
            extraction_method="sampled-line-window",
            metadata={"byte_ranges": ranges, "file_size": file_size},
        )]

    def _read_structured(self, path: Path, relative_path: str, candidate: CandidateFile, request: RetrievalRequest) -> list[EvidencePassage]:
        parser = self.registry.get_parser(path.suffix)
        if parser is None:
            return []
        try:
            document = parser.parse(path, f"read-{uuid.uuid4().hex}")
        except Exception:
            return []

        terms = self._terms(request.query)
        scored_sections = []
        for index, section in enumerate(document.sections):
            section_text = section.text or ""
            haystack = f"{section.heading or ''}\n{section_text}".lower()
            score = sum(haystack.count(term) for term in terms)
            scored_sections.append((score, index, section))
        scored_sections.sort(key=lambda item: (-item[0], item[1]))

        passages: list[EvidencePassage] = []
        for score, _, section in scored_sections[:6]:
            text = (section.text or "").strip()
            if not text:
                continue
            text = text[:request.max_bytes_per_read]
            page = section.page or section.metadata.get("page")
            section_name = section.heading or section.sheet or (f"Slide {section.slide}" if section.slide else None)
            passages.append(EvidencePassage(
                evidence_id=f"ev-{uuid.uuid4().hex[:10]}",
                relative_path=relative_path,
                text=text,
                reason="Structured section matched query" if score else "Selected candidate section",
                heading=section_name,
                page=page,
                extraction_method="parser-section",
                metadata={"score": score, **(section.metadata or {})},
            ))
        if not passages and candidate.relevant_preview:
            passages.append(EvidencePassage(
                evidence_id=f"ev-{uuid.uuid4().hex[:10]}",
                relative_path=relative_path,
                text=candidate.relevant_preview,
                reason="Bounded candidate preview",
                extraction_method="candidate-preview",
            ))
        return passages

    @staticmethod
    def _terms(query: str) -> list[str]:
        return [term for term in re.findall(r"[a-zA-Z0-9_]+", query.lower()) if len(term) > 1]

    @staticmethod
    def _contiguous_groups(values: list[int]) -> list[tuple[int, int]]:
        if not values:
            return []
        groups: list[tuple[int, int]] = []
        start = previous = values[0]
        for value in values[1:]:
            if value != previous + 1:
                groups.append((start, previous))
                start = value
            previous = value
        groups.append((start, previous))
        return groups

    @staticmethod
    def _heading_for(lines: list[tuple[int, str]], index: int) -> str | None:
        for _, line in reversed(lines[max(0, index - 20): index + 1]):
            match = re.match(r"^\s{0,3}#{1,6}\s+(.+)$", line)
            if match:
                return match.group(1).strip()
        return None
