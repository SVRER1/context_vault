"""Deterministic bounded candidate selection (legacy selector name retained)."""

from contextvault.retrieval.filesystem_models import CandidateFile, RetrievalRequest


class AgentCandidateSelector:
    """Select the highest-ranked candidates without a generative dependency."""

    def __init__(self, llm_client=None):
                                                                                         
        self._legacy_argument_ignored = llm_client is not None

    def select(self, request: RetrievalRequest, candidates: list[CandidateFile]) -> list[CandidateFile]:
        if not candidates:
            return []
        return candidates[:request.max_deep_reads]
