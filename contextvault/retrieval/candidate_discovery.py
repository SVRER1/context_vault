"""Cheap lexical, path, metadata, and preview candidate discovery."""

import re
from pathlib import Path

from contextvault.core.vault import Vault
from contextvault.retrieval.filesystem_models import CandidateFile, FileSurvey
from contextvault.retrieval.filesystem_policy import validate_source_scope


STOP_WORDS = {
    "a", "an", "and", "are", "about", "by", "does", "for", "from", "how",
    "in", "is", "of", "on", "or", "that", "the", "this", "to", "what", "with",
}

CONTROLLED_EXPANSIONS = {
    "authentication": {"auth", "login", "session", "token", "credential", "oauth", "jwt"},
    "auth": {"authentication", "login", "session", "token", "credential"},
    "exception": {"error", "throw", "catch", "handling", "failure"},
    "exceptions": {"exception", "error", "throw", "catch", "handling", "failure"},
    "streaming": {"stream", "chunk", "loading", "pipeline"},
    "search": {"retrieval", "query", "lookup", "find"},
    "generation": {"artifact", "summary", "guide", "output"},
}


TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".log", ".py", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".rs", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml",
    ".toml", ".xml", ".sql", ".sh", ".ps1", ".csv", ".tsv",
}


class CandidateDiscovery:
    """Rank files without requiring an embedding or vector database."""

    def __init__(self, vault: Vault, preview_bytes: int = 16_384):
        self.vault = vault
        self.preview_bytes = preview_bytes

    def discover(
        self,
        query: str,
        surveys: list[FileSurvey],
        source_scope: str | None = None,
        max_candidates: int = 20,
        hints: tuple[str, ...] = (),
    ) -> list[CandidateFile]:
        validate_source_scope(self.vault, source_scope)
        terms = self.expand_terms(query, hints=hints)
        phrase = self._normalise(query)
        candidates: list[CandidateFile] = []

        for survey in surveys:
            path_lower = self._normalise(survey.relative_path)
            filename_lower = self._normalise(survey.filename)
            preview = survey.preview or ""
            cheap_text = preview
            if survey.extension in TEXT_EXTENSIONS:
                cheap_text = self._read_search_windows(survey.relative_path, survey.size, self.preview_bytes)
            text_lower = self._normalise(cheap_text)

            score = 0.0
            reasons: list[str] = []
            matched: list[str] = []
            if phrase and phrase in path_lower:
                score += 1.0
                reasons.append("exact phrase in path")
            for term in terms:
                path_hits = path_lower.count(term)
                text_hits = text_lower.count(term)
                if path_hits:
                    score += 0.55 * min(path_hits, 3)
                    matched.append(term)
                    reasons.append(f"path matches '{term}'")
                if text_hits:
                    score += 0.35 * min(text_hits, 5)
                    if term not in matched:
                        matched.append(term)
                    reasons.append(f"content preview matches '{term}'")

            if survey.parser:
                parser_hint = self._normalise(survey.parser.replace("Parser", ""))
                if any(term in parser_hint for term in terms):
                    score += 0.1
                    reasons.append("parser metadata matches query")

            if score <= 0:
                continue
            relevant_preview = self._relevant_preview(cheap_text, terms)
            candidates.append(CandidateFile(
                survey=survey,
                score=min(score, 5.0),
                reasons=self._dedupe(reasons),
                relevant_preview=relevant_preview,
                matched_terms=self._dedupe(matched),
            ))

        candidates.sort(key=lambda candidate: (-candidate.score, candidate.survey.relative_path.lower()))
        return candidates[:max_candidates]

    def expand_terms(self, query: str, hints: tuple[str, ...] = ()) -> list[str]:
        base = [term for term in re.findall(r"[a-zA-Z0-9_]+", self._normalise(query)) if term not in STOP_WORDS and len(term) > 1]
        expanded = list(dict.fromkeys(base))
        for term in base:
            expanded.extend(sorted(CONTROLLED_EXPANSIONS.get(term, set())))
        for hint in hints:
            expanded.extend(
                term for term in re.findall(r"[a-zA-Z0-9_]+", self._normalise(hint))
                if term not in STOP_WORDS and len(term) > 1
            )
        return list(dict.fromkeys(expanded))[:16]

    def _read_search_windows(self, relative_path: str, file_size: int, max_bytes: int) -> str:
        path = self.vault.absolute_path(relative_path)
        try:
            if file_size <= max_bytes:
                return path.read_text(encoding="utf-8", errors="ignore")[:max_bytes]
            window_size = max(1024, max_bytes // 4)
            starts = {0, max(0, file_size - window_size), file_size // 3, (file_size * 2) // 3}
            windows = []
            with path.open("rb") as handle:
                for start in sorted(starts):
                    handle.seek(start)
                    windows.append(handle.read(window_size).decode("utf-8", errors="ignore"))
            return "\n".join(windows)
        except (OSError, UnicodeError):
            return ""

    @staticmethod
    def _relevant_preview(text: str, terms: list[str], max_chars: int = 1200) -> str:
        if not text:
            return ""
        lines = text.splitlines()
        matching_indexes = [
            index for index, line in enumerate(lines)
            if any(term in line.lower() for term in terms)
        ]
        if not matching_indexes:
            return text[:max_chars].strip()
        selected: list[str] = []
        used: set[int] = set()
        for index in matching_indexes[:8]:
            for line_index in range(max(0, index - 1), min(len(lines), index + 2)):
                if line_index not in used:
                    selected.append(lines[line_index])
                    used.add(line_index)
        return "\n".join(selected)[:max_chars].strip()

    @staticmethod
    def _normalise(value: str) -> str:
        return re.sub(r"[^a-z0-9_./-]+", " ", value.lower())

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
