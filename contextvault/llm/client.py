"""Abstract base class for LLM clients."""

from abc import ABC, abstractmethod
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    def generate(self, prompt: str, system: str | None = None, temperature: float = 0.3) -> str:
        """Generate text from a prompt."""
        ...

    @abstractmethod
    def generate_structured(self, prompt: str, system: str | None, schema: Type[T]) -> T:
        """Generate structured output validated against a Pydantic schema."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the LLM backend is available."""
        ...

    @abstractmethod
    def get_model_info(self) -> dict:
        """Get information about the current model."""
        ...
