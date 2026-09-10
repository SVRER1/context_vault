"""Query-scoped evidence Markdown and provenance construction."""

import json
import uuid
from pathlib import Path

from contextvault.core.config import AppConfig, get_config
from contextvault.core.vault import Vault
from contextvault.retrieval.filesystem_models import (
    CandidateFile,
    EvidenceDocument,
    EvidencePassage,
    RetrievalRequest,
)
from contextvault.retrieval.filesystem_policy import validate_source_scope


class EvidenceBuilder:
    """Build compact, attributed evidence without changing the source vault."""

    def __init__(self, vault: Vault, config: AppConfig | None = None):
        self.vault = vault
        self.config = config or get_config()

    def build(
        self,
        request: RetrievalRequest,
        passages: list[EvidencePassage],
        candidates: list[CandidateFile] | None = None,
    ) -> EvidenceDocument:
        validate_source_scope(self.vault, request.source_scope)
        request_id = f"retrieval-{uuid.uuid4().hex}"
        runtime_dir = self.config.vault_data_dir(request.vault_id) / "runtime" / "retrieval" / request_id
        runtime_dir.mkdir(parents=True, exist_ok=True)

        valid_passages: list[EvidencePassage] = []
        seen = set()
        for passage in passages:
            if not self.vault.is_in_scope(passage.relative_path, request.source_scope):
                continue
            if Path(passage.relative_path).parts and any(
                part.lower() == self.config.generated_output_folder.lower()
                for part in Path(passage.relative_path).parts
            ):
                continue
            key = (passage.relative_path, passage.heading, passage.page, passage.line_start, passage.text.strip())
            if not passage.text.strip() or key in seen:
                continue
            seen.add(key)
            valid_passages.append(passage)

        sufficient = bool(valid_passages)
        insufficiency_reason = None if sufficient else (
            f"No sufficient evidence was found inside {request.source_scope or 'the entire vault'}."
        )
        markdown = self._render(request, valid_passages, insufficiency_reason)

        self._write_json(runtime_dir / "request.json", {
            "request_id": request_id,
            "query": request.query,
            "vault_id": request.vault_id,
            "source_scope": request.source_scope,
            "operation": request.operation,
            "limits": {
                "context_budget": request.context_budget,
                "max_rounds": request.max_rounds,
                "max_candidates": request.max_candidates,
                "max_deep_reads": request.max_deep_reads,
            },
        })
        self._write_json(runtime_dir / "candidates.json", [self._candidate_dict(item) for item in (candidates or [])])
        self._write_json(runtime_dir / "sources.json", {
            "request_id": request_id,
            "vault_id": request.vault_id,
            "source_scope": request.source_scope,
            "query": request.query,
            "sources": [self._passage_dict(item) for item in valid_passages],
        })
        (runtime_dir / "evidence.md").write_text(markdown, encoding="utf-8")
        self._write_json(runtime_dir / "result.json", {
            "request_id": request_id,
            "sufficient": sufficient,
            "evidence_count": len(valid_passages),
        })

        return EvidenceDocument(
            request_id=request_id,
            query=request.query,
            source_scope=request.source_scope,
            markdown=markdown,
            passages=valid_passages,
            runtime_dir=str(runtime_dir),
            sufficient=sufficient,
            insufficiency_reason=insufficiency_reason,
        )

    def _render(self, request: RetrievalRequest, passages: list[EvidencePassage], insufficiency_reason: str | None) -> str:
        lines = [
            "# Context Vault Query Evidence",
            "",
            "## Query",
            request.query,
            "",
            "## Active Source Scope",
            request.source_scope or "Entire Vault",
            "",
        ]
        if not passages:
            lines.extend(["## Evidence Status", insufficiency_reason or "No evidence.", ""])
            return "\n".join(lines)

        used = 0
        for index, passage in enumerate(passages, start=1):
            location = []
            if passage.heading:
                location.append(f"heading={passage.heading}")
            if passage.page is not None:
                location.append(f"page={passage.page}")
            if passage.line_start is not None:
                location.append(f"lines={passage.line_start}-{passage.line_end}")
            if passage.metadata.get("byte_ranges"):
                location.append(f"byte_ranges={passage.metadata['byte_ranges']}")
            location_text = ", ".join(location) or "location not available"
            remaining = max(0, request.context_budget - used)
            if remaining <= 0:
                break
            text = passage.text[:remaining].strip()
            if not text:
                continue
            lines.extend([
                f"## Evidence {index}",
                "",
                f"Source: `{passage.relative_path}`",
                f"Location: {location_text}",
                f"Extraction method: `{passage.extraction_method}`",
                f"Reason Selected: {passage.reason}",
                "",
                "Relevant Evidence:",
                "```text",
                text,
                "```",
                "",
            ])
            used += len(text)
        return "\n".join(lines)

    @staticmethod
    def _candidate_dict(candidate: CandidateFile) -> dict:
        return {
            "relative_path": candidate.survey.relative_path,
            "filename": candidate.survey.filename,
            "extension": candidate.survey.extension,
            "directory": candidate.survey.directory,
            "size": candidate.survey.size,
            "mtime": candidate.survey.mtime,
            "parser": candidate.survey.parser,
            "score": candidate.score,
            "reasons": candidate.reasons,
            "matched_terms": candidate.matched_terms,
            "relevant_preview": candidate.relevant_preview,
        }

    @staticmethod
    def _passage_dict(passage: EvidencePassage) -> dict:
        return {
            "evidence_id": passage.evidence_id,
            "relative_path": passage.relative_path,
            "heading": passage.heading,
            "page": passage.page,
            "line_start": passage.line_start,
            "line_end": passage.line_end,
            "reason": passage.reason,
            "extraction_method": passage.extraction_method,
        }

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
