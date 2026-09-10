from pydantic import BaseModel
from typing import List, Optional
from contextvault.core.models import FileRecord

class DuplicateGroup(BaseModel):
    """Group of duplicated or related version files."""
    group_type: str
    hash: Optional[str] = None
    files: List[FileRecord]
    confidence: float
    reason: str
