"""Filesystem-Native Agentic Retrieval public API."""

from contextvault.retrieval.filesystem_models import EvidenceDocument, RetrievalRequest
from contextvault.retrieval.filesystem_service import FilesystemRetrievalService

__all__ = ["EvidenceDocument", "RetrievalRequest", "FilesystemRetrievalService"]
from contextvault.retrieval.filesystem_models import RetrievalRequest, EvidenceDocument
from contextvault.retrieval.filesystem_service import FilesystemRetrievalService

__all__ = ["RetrievalRequest", "EvidenceDocument", "FilesystemRetrievalService"]
