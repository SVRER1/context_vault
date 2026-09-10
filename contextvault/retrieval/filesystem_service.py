"""Filesystem-native, directory-scoped retrieval and evidence service."""

import logging
import time
from collections import Counter

from contextvault.core.config import AppConfig, get_config
from contextvault.core.vault import Vault
from contextvault.retrieval.agent_selection import AgentCandidateSelector
from contextvault.retrieval.candidate_discovery import CandidateDiscovery
from contextvault.retrieval.evidence import EvidenceBuilder
from contextvault.retrieval.filesystem_models import (
    CandidateFile,
    EvidenceDocument,
    RetrievalRequest,
)
from contextvault.retrieval.filesystem_policy import validate_source_scope
from contextvault.retrieval.filesystem_survey import FilesystemSurvey
from contextvault.retrieval.selective_reader import SelectiveReader

logger = logging.getLogger(__name__)


class FilesystemRetrievalService:
    """Survey, rank, selectively read, and construct query evidence."""

    def __init__(self, vault: Vault, llm_client=None, config: AppConfig | None = None, ocr_client=None):
        self.vault = vault
        self.llm_client = llm_client
        self.config = config or get_config()
        self.ocr_client = ocr_client if ocr_client is not None else llm_client
        self.survey_service = FilesystemSurvey(vault, config=self.config)
        self.discovery = CandidateDiscovery(vault, preview_bytes=self.config.retrieval_preview_bytes)
        self.selector = AgentCandidateSelector(llm_client)
        self.reader = SelectiveReader(vault, ocr_client=self.ocr_client)
        self.evidence_builder = EvidenceBuilder(vault, config=self.config)

    def retrieve(self, request: RetrievalRequest) -> EvidenceDocument:
        """Run one bounded retrieval request against the selected scope."""
        if request.vault_id != self.vault.vault_id:
            raise ValueError("Retrieval request vault does not match the active vault.")
        validate_source_scope(self.vault, request.source_scope, self.config.generated_output_folder)
        started = time.perf_counter()
        surveys = self.survey_service.survey(request.source_scope)
        candidates = self.discovery.discover(
            request.query,
            surveys,
            source_scope=request.source_scope,
            max_candidates=request.max_candidates,
            hints=request.hints,
        )
        selected: list[CandidateFile] = []
        passages = []
        read_paths: set[str] = set()
        rounds = 0

        while rounds < request.max_rounds:
            rounds += 1
            selected = self.selector.select(request, candidates)
            for candidate in selected:
                if len(passages) >= request.max_deep_reads * 6:
                    break
                if candidate.survey.relative_path in read_paths:
                    continue
                read_paths.add(candidate.survey.relative_path)
                passages.extend(self.reader.read(candidate, request))
            if passages or rounds >= request.max_rounds:
                break
                                                                        
                                                                           
            extra_hints = tuple(self.discovery.expand_terms(request.query))
            candidates = self.discovery.discover(
                request.query,
                surveys,
                source_scope=request.source_scope,
                max_candidates=request.max_candidates,
                hints=extra_hints,
            )

        evidence = self.evidence_builder.build(request, passages, candidates=candidates)
        logger.info(
            "Filesystem retrieval request_id=%s vault=%s scope=%s survey=%d candidates=%d selected=%d rounds=%d evidence=%d sufficient=%s duration_ms=%.1f",
            evidence.request_id,
            request.vault_id,
            request.source_scope or "<entire-vault>",
            len(surveys),
            len(candidates),
            len(selected),
            rounds,
            len(evidence.passages),
            evidence.sufficient,
            (time.perf_counter() - started) * 1000,
        )
        return evidence

    def search(self, request: RetrievalRequest) -> list[CandidateFile]:
        """Discover and rank results without constructing answer evidence."""
        if request.vault_id != self.vault.vault_id:
            raise ValueError("Search request vault does not match the active vault.")
        validate_source_scope(self.vault, request.source_scope, self.config.generated_output_folder)
        surveys = self.survey_service.survey(request.source_scope)
        return self.discovery.discover(
            request.query,
            surveys,
            source_scope=request.source_scope,
            max_candidates=request.max_candidates,
            hints=request.hints,
        )

    def scope_summary(self, source_scope: str | None = None) -> dict:
        """Return deterministic topology statistics for reports and diagnostics."""
        validate_source_scope(self.vault, source_scope, self.config.generated_output_folder)
        surveys = self.survey_service.survey(source_scope)
        return {
            "source_scope": source_scope,
            "file_count": len(surveys),
            "mime_families": dict(Counter(item.mime_family for item in surveys)),
            "parser_counts": dict(Counter(item.parser or "unsupported" for item in surveys)),
        }
