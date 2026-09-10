from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from contextvault.core.models import Citation

class AgentResult(BaseModel):
    result_type: str = Field(..., description="answer, search_results, organisation_plan, generated_file, duplicates, status, error")
    content: str
    data: Optional[Dict[str, Any]] = None
    citations: List[Citation] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
