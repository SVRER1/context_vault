"""Pydantic models for structured LLM generation with small-model resilience."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class IntentClassification(BaseModel):
    intent: str = Field(..., description="rag_query, search, organise, generate, duplicates, status, peek_directory, generate_chart, unknown")
    confidence: float = 0.8
    parameters: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters", mode="before")
    @classmethod
    def normalize_parameters(cls, v: Any) -> Dict[str, Any]:
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            return {"query": v}
        return {}


class FileClassification(BaseModel):
    category: str
    document_type: str = "Document"
    confidence: float = 0.8
    evidence: List[str] = Field(default_factory=list)

    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_evidence(cls, v: Any) -> List[str]:
        if isinstance(v, list):
            return [str(item) for item in v]
        if isinstance(v, str):
            return [v]
        return []


class QueryRewrite(BaseModel):
    rewritten_query: str
    search_terms: List[str] = Field(default_factory=list)

    @field_validator("search_terms", mode="before")
    @classmethod
    def normalize_terms(cls, v: Any) -> List[str]:
        if isinstance(v, list):
            return [str(item) for item in v]
        if isinstance(v, str):
            return [v]
        return []


class OrganisationSuggestion(BaseModel):
    category: str
    subcategory: Optional[str] = None
    confidence: float = 0.8
    reasoning: str = ""


class GenerationPlan(BaseModel):
    title: str
    outline: List[str] = Field(default_factory=list)
    source_queries: List[str] = Field(default_factory=list)
