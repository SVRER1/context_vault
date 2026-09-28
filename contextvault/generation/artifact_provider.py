"""Optional model boundary for generated text artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from contextvault.core.exceptions import OllamaUnavailableError


@dataclass(frozen=True)
class ArtifactRequest:
    artifact_type: str
    prompt: str
    evidence: str
    source_scope: str | None = None


class ArtifactProvider(Protocol):
    """A provider receives a bounded prompt and already selected evidence."""

    def generate(self, request: ArtifactRequest) -> str: ...


class OllamaArtifactProvider:
    """Lazy adapter that constructs/checks Ollama only for explicit generation."""

    def __init__(self, client_factory):
        self._client_factory = client_factory
        self._client: Any = None
        self._checked = False
        self._available: bool | None = None

    @property
    def availability_checked(self) -> bool:
        return self._available is not None

    @property
    def available(self) -> bool | None:
        return self._available

    def _get_client(self):
        if not self._checked:
            self._checked = True
            self._client = self._client_factory()
        if self._client is None:
            self._available = False
            raise OllamaUnavailableError("Ollama is unavailable; generated synthesis cannot run.")
        try:
            self._available = bool(self._client.is_available())
            if not self._available:
                raise OllamaUnavailableError("Ollama is offline; generated synthesis cannot run.")
        except OllamaUnavailableError:
            raise
        except Exception as exc:
            self._available = False
            raise OllamaUnavailableError(f"Could not reach the configured artifact provider: {exc}") from exc
        return self._client

    def generate(self, request: ArtifactRequest) -> str:
        client = self._get_client()
        try:
            return client.generate(request.prompt)
        except Exception as exc:
            raise OllamaUnavailableError(f"Artifact generation failed: {exc}") from exc


class ExistingLLMAdapter:
    """Wrap an explicitly injected legacy client behind the artifact contract."""

    def __init__(self, client):
        self.client = client

    def generate(self, request: ArtifactRequest) -> str:
        if self.client is None or not self.client.is_available():
            raise OllamaUnavailableError("No artifact provider is available for generation.")
        try:
            return self.client.generate(request.prompt)
        except Exception as exc:
            raise OllamaUnavailableError(f"Artifact generation failed: {exc}") from exc
