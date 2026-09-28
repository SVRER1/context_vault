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
from contextvault.retrieval.search_models import SearchRequest
from contextvault.retrieval.search_service import SearchService

logger = logging.getLogger(__name__)


class RAGService:
    """Answer and search against live, scope-bound filesystem evidence."""

    def __init__(
        self,
        retriever: Any = None,  
        llm_client: Any = None,
        vault: Vault | None = None,
        retrieval_service: FilesystemRetrievalService | None = None,
        search_service: SearchService | None = None,
        artifact_provider: Any = None,
    ):
        self.llm_client = llm_client
        if artifact_provider is None and llm_client is not None:
            from contextvault.generation.artifact_provider import ExistingLLMAdapter
            artifact_provider = ExistingLLMAdapter(llm_client)
        self.artifact_provider = artifact_provider
        self.vault = vault
        self.config = get_config()
        self.retrieval_service = retrieval_service or (
            FilesystemRetrievalService(vault, llm_client=llm_client, config=self.config)
            if vault is not None else None
        )
        self.search_service = search_service

    def ask(self, question: str, vault_id: str, subfolder: str | None = None) -> RAGResponse:
        """Return ranked evidence and excerpts without generating an answer."""
        if self.search_service is not None:
            response = self.search_service.search(SearchRequest(
                vault_id=vault_id, query=question, source_scope=subfolder, limit=10
            ))
            citations = []
            blocks = []
            for hit in response.hits:
                for passage in hit.passages[:2]:
                    location = []
                    if passage.page is not None:
                        location.append(f"page {passage.page}")
                    if passage.heading:
                        location.append(passage.heading)
                    if passage.line_start is not None:
                        location.append(f"lines {passage.line_start}-{passage.line_end}")
                    section = ", ".join(location) or None
                    blocks.append(f"[{hit.relative_path}{', ' + section if section else ''}]\n{passage.snippet}")
                    citations.append(Citation(
                        file_path=hit.relative_path,
                        page=passage.page,
                        section=section,
                        heading=passage.heading,
                        chunk_text_preview=passage.snippet,
                    ))
            if not blocks:
                message = "No matching evidence was found in the indexed files."
                if response.unknown_ids:
                    message += f" {len(response.unknown_ids)} file(s) have incomplete or unavailable extraction."
                return RAGResponse(answer=message, sources=[], confidence=0.0)
            return RAGResponse(
                answer=f"Retrieved evidence for: {question}\n\n" + "\n\n".join(blocks),
                sources=citations,
                confidence=0.7 if len(citations) > 1 else 0.5,
            )

        if self.retrieval_service is None:
            raise ValueError("Retrieval service is unavailable.")
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
        return RAGResponse(
            answer=evidence.markdown if evidence.sufficient else (
                evidence.insufficiency_reason or "No sufficient source evidence was found."
            ),
            sources=self._citations_from_evidence(evidence),
            confidence=0.6 if evidence.sufficient else 0.0,
        )

    def synthesize(self, question: str, vault_id: str, subfolder: str | None = None) -> RAGResponse:
        """Explicit model-backed answer generation from retrieved evidence."""
        if self.artifact_provider is None:
            raise OllamaUnavailableError("No artifact provider is available for synthesis.")
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
        prompt = EVIDENCE_ANSWER_PROMPT.format(
            question=question,
            source_scope=subfolder or "Entire Vault",
            evidence=evidence.markdown,
        )
        from contextvault.generation.artifact_provider import ArtifactRequest
        answer = self.artifact_provider.generate(ArtifactRequest(
            artifact_type="answer",
            prompt=prompt,
            evidence=evidence.markdown,
            source_scope=subfolder,
        ))
        return RAGResponse(
            answer=answer.strip(),
            sources=self._citations_from_evidence(evidence),
            confidence=0.8 if len(evidence.passages) >= 2 else 0.6,
        )

    def search(
        self, query: str, vault_id: str, top_k: int = 10, subfolder: str | None = None
    ) -> list[SearchResult]:
        if self.search_service is not None:
            response = self.search_service.search(SearchRequest(
                vault_id=vault_id, query=query, source_scope=subfolder, limit=top_k
            ))
            return [SearchResult(
                file_id=hit.file_id,
                relative_path=hit.relative_path,
                filename=hit.filename,
                snippet=hit.passages[0].snippet if hit.passages else hit.filename,
                page=hit.passages[0].page if hit.passages else None,
                section=hit.passages[0].heading or hit.passages[0].section if hit.passages else None,
                score=hit.score,
            ) for hit in response.hits]
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
