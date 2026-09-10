"""Ollama client for text and image-aware local models."""

import json
import base64
import logging
import re
from pathlib import Path
from typing import Any, Generator, Type, TypeVar

import requests
from pydantic import BaseModel

from contextvault.llm.client import LLMClient
from contextvault.core.exceptions import LLMConnectionError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemma4:e2b"


class OllamaClient(LLMClient):
    """Client for interacting with a local Ollama instance."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = DEFAULT_MODEL,
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.requested_model = model
        self.timeout = timeout
        self._resolved_model: str | None = None

    @property
    def model(self) -> str:
        """Get the resolved model name, matching against installed Ollama models."""
        if self._resolved_model is None:
            self._resolved_model = self._resolve_model_name(self.requested_model)
        return self._resolved_model

    @model.setter
    def model(self, value: str):
        self.requested_model = value
        self._resolved_model = self._resolve_model_name(value)

    def _resolve_model_name(self, target: str) -> str:
        """Resolve a friendly model name (e.g. 'lfm2.5' or 'lfm2.5:1.2b') to the exact tag in Ollama."""
        try:
            available = self.list_models()
            if not available:
                return target

                         
            if target in available:
                return target

                                              
            target_lower = target.lower()
            for name in available:
                if name.lower() == target_lower:
                    return name

                                       
            for name in available:
                if target_lower in name.lower() or name.lower() in target_lower:
                    return name

            return target
        except Exception:
            return target

    def list_models(self) -> list[str]:
        """Fetch all installed models from local Ollama instance."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                models = response.json().get("models", [])
                return [m.get("name", "") for m in models if m.get("name")]
            return []
        except requests.RequestException:
            return []

    def generate(
        self, prompt: str, system: str | None = None, temperature: float = 0.2
    ) -> str:
        """Generate a text response from the configured Ollama model."""
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "num_ctx": 2048,
            },
        }
        if system:
            payload["system"] = system

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()
        except requests.ConnectionError:
            raise LLMConnectionError("Cannot connect to Ollama. Ensure Ollama service is running.")
        except requests.Timeout:
            raise LLMConnectionError(f"Ollama request timed out after {self.timeout}s.")
        except requests.RequestException as e:
            raise LLMConnectionError(f"Ollama generation failed: {e}")

    def ocr_image(self, image_path: str | Path) -> str:
        """Extract visible text from an image using Ollama's vision input.

        Ollama accepts image bytes as base64 in the ``images`` field for
        multimodal models. The method is intentionally separate from
        ``generate`` so image understanding is explicit and auditable.
        """
        path = Path(image_path)
        try:
            image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": (
                        "Transcribe all legible text in this image exactly. "
                        "Preserve line breaks where practical. Return only the transcription. "
                        "If there is no readable text, return an empty response."
                    ),
                    "images": [image_b64],
                    "stream": False,
                    "options": {"temperature": 0, "num_ctx": 2048},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()
        except requests.ConnectionError:
            raise LLMConnectionError("Cannot connect to Ollama for image OCR.")
        except requests.Timeout:
            raise LLMConnectionError(f"Ollama image OCR timed out after {self.timeout}s.")
        except (OSError, requests.RequestException, ValueError) as e:
            raise LLMConnectionError(f"Ollama image OCR failed: {e}")

    def generate_stream(
        self, prompt: str, system: str | None = None, temperature: float = 0.2
    ) -> Generator[str, None, None]:
        """Stream generated text token by token from Ollama."""
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "num_ctx": 2048,
            },
        }
        if system:
            payload["system"] = system

        try:
            with requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=True,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        chunk = json.loads(line.decode("utf-8"))
                        text = chunk.get("response", "")
                        if text:
                            yield text
        except requests.RequestException as e:
            raise LLMConnectionError(f"Ollama streaming error: {e}")

    def generate_structured(
        self, prompt: str, system: str | None, schema: Type[T]
    ) -> T:
        """Generate structured JSON output validated against a Pydantic schema."""
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_ctx": 2048,
            },
        }
        if system:
            payload["system"] = system

        for attempt in range(2):
            try:
                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                result_text = response.json().get("response", "{}").strip()

                                                                              
                clean_json = self._extract_json_string(result_text)
                return schema.model_validate_json(clean_json)
            except Exception as e:
                if attempt == 1:
                    logger.warning(f"Structured generation attempt {attempt+1} failed: {e}")
                                                                               
                    raise LLMConnectionError(f"Structured generation failed: {e}")
                logger.debug(f"Retrying structured generation after error: {e}")

    @staticmethod
    def _extract_json_string(text: str) -> str:
        """Extract valid JSON from raw text or markdown fences."""
        text = text.strip()
                                       
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fence_match:
            return fence_match.group(1).strip()
                                           
        brace_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if brace_match:
            return brace_match.group(1).strip()
        return text

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            models = self.list_models()
            if not models:
                return False
                                                                               
            req = self.requested_model.lower()
            return any(req == m.lower() or req in m.lower() or m.lower() in req for m in models)
        except Exception:
            return False

    def get_model_info(self) -> dict:
        """Get information about the configured model from Ollama."""
        try:
            response = requests.post(
                f"{self.base_url}/api/show",
                json={"name": self.model},
                timeout=5,
            )
            if response.status_code == 200:
                return response.json()
        except requests.RequestException:
            pass
        return {}
