"""Filesystem-native question answering and candidate search."""

import logging
from typing import Any

from contextvault.core.config import get_config
from contextvault.core.exceptions import OllamaUnavailableError
from contextvault.core.models import Citation, RAGResponse, SearchResult
from contextvault.core.vault import Vault
from contextvault.llm.prompts import EVIDENCE_ANSWER_PROMPT
from contextvault.retrieval.filesystem_models import RetrievalRequest
from contextvault.retrieval.filesystem_service import FilesystemRetrievalService

logger = logging.getLogger(__name__)


class RAGService:
    """Answer and search against live, scope-bound filesystem evidence."""

    def __init__(
        self,
        retriever: Any = None,                                                 
        llm_client: Any = None,
        vault: Vault | None = None,
        retrieval_service: FilesystemRetrievalService | None = None,
    ):
        self.llm_client = llm_client
        self.vault = vault
        self.config = get_config()
        self.retrieval_service = retrieval_service or (
            FilesystemRetrievalService(vault, llm_client=llm_client, config=self.config)
            if vault is not None else None
        )

    def ask(self, question: str, vault_id: str, subfolder: str | None = None) -> RAGResponse:
        if self.retrieval_service is None:
            raise ValueError("Filesystem retrieval service is unavailable.")

        request = RetrievalRequest(
            query=question,
            vault_id=vault_id,
            source_scope=subfolder,
            operation="ask",
            output_type="answer",
            context_budget=self.config.retrieval_context_budget,
            max_rounds=self.config.retrieval_max_rounds,
            max_candidates=self.config.retrieval_max_candidates,
            max_deep_reads=self.config.retrieval_max_deep_reads,
            max_bytes_per_read=self.config.retrieval_max_bytes_per_read,
        )
        evidence = self.retrieval_service.retrieve(request)
        if not evidence.sufficient:
            return RAGResponse(
                answer=evidence.insufficiency_reason or "The selected source scope does not contain enough information.",
                sources=[],
                confidence=0.0,
            )
        if self.llm_client is None:
            raise OllamaUnavailableError(
                "Local LLM is not available. Search remains available without it."
            )

        prompt = EVIDENCE_ANSWER_PROMPT.format(
            question=question,
            source_scope=subfolder or "Entire Vault",
            evidence=evidence.markdown,
        )
        try:
            answer = self.llm_client.generate(prompt=prompt, temperature=self.config.temperature)
        except Exception as exc:
            raise OllamaUnavailableError(f"Failed to generate answer: {exc}")
        return RAGResponse(
            answer=answer.strip(),
            sources=self._citations_from_evidence(evidence),
            confidence=0.8 if len(evidence.passages) >= 2 else 0.6,
        )

    def search(
        self, query: str, vault_id: str, top_k: int = 10, subfolder: str | None = None
    ) -> list[SearchResult]:
        if self.retrieval_service is None:
            return []
        request = RetrievalRequest(
            query=query,
            vault_id=vault_id,
            source_scope=subfolder,
            operation="search",
            output_type="search_results",
            max_candidates=top_k,
        )
        candidates = self.retrieval_service.search(request)
        return [
            SearchResult(
                file_id="",
                relative_path=candidate.survey.relative_path,
                filename=candidate.survey.filename,
                snippet=(candidate.relevant_preview or candidate.survey.preview)[:300],
                section=None,
                score=candidate.score,
            )
            for candidate in candidates
        ]

    @staticmethod
    def _citations_from_evidence(evidence) -> list[Citation]:
        citations = []
        seen = set()
        for passage in evidence.passages:
            key = (passage.relative_path, passage.heading, passage.page, passage.line_start)
            if key in seen:
                continue
            seen.add(key)
            section = passage.heading
            if passage.line_start is not None:
                section = f"{section or 'lines'} ({passage.line_start}-{passage.line_end})"
            citations.append(Citation(
                file_path=passage.relative_path,
                page=passage.page,
                section=section,
                heading=passage.heading,
                chunk_text_preview=passage.text[:150].strip() + ("..." if len(passage.text) > 150 else ""),
            ))
        return citations

