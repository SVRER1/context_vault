from datetime import datetime
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any

class VaultInfo(BaseModel):
    id: str
    display_name: str
    absolute_path: str
    created_at: datetime
    last_opened_at: datetime
    last_indexed_at: Optional[datetime] = None
    file_count: int = 0
    chunk_count: int = 0
    index_version: int = 1

class FileRecord(BaseModel):
    id: str
    vault_id: str
    relative_path: str
    filename: str
    extension: str
    size: int
    mtime: float
    created_time: float
    sha256: str
    mime_family: str
    parser: Optional[str] = None
    parse_status: str = "pending"
    indexed_at: Optional[datetime] = None

class ChunkRecord(BaseModel):
    id: str
    file_id: str
    vault_id: str
    relative_path: str
    chunk_index: int
    text: str
    page: Optional[int] = None
    section: Optional[str] = None
    heading: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def handle_content_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "text" not in data and "content" in data:
                data["text"] = data["content"]
            if "heading" not in data and "section_title" in data:
                data["heading"] = data["section_title"]
        return data

class DocumentSection(BaseModel):
    heading: Optional[str] = None
    text: str = ""
    page: Optional[int] = None
    slide: Optional[int] = None
    sheet: Optional[str] = None
    cell_range: Optional[str] = None
    level: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def handle_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
                                     
            if "text" not in data and "content" in data:
                data["text"] = data["content"]
                                      
            if "heading" not in data and "title" in data:
                data["heading"] = data["title"]
                                                              
            meta = data.get("metadata", {})
            if isinstance(meta, dict):
                if "page" in meta and data.get("page") is None:
                    data["page"] = meta["page"]
                if "heading" in meta and data.get("heading") is None:
                    data["heading"] = meta["heading"]
                if "sheet" in meta and data.get("sheet") is None:
                    data["sheet"] = meta["sheet"]
        return data

class ParsedDocument(BaseModel):
    file_id: str
    path: str = ""
    title: Optional[str] = None
    text: str = ""
    sections: List[DocumentSection] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def handle_content_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "text" not in data and "content" in data:
                data["text"] = data["content"]
        return data

class OperationRecord(BaseModel):
    operation_id: str
    timestamp: datetime
    vault_id: str
    operation_type: str
    source_path: str
    destination_path: Optional[str] = None
    hash_before: Optional[str] = None
    hash_after: Optional[str] = None
    status: str
    reason: Optional[str] = None
    user_approved: bool = False
    batch_id: Optional[str] = None
    undo_status: str = "none"

class PlannedOperation(BaseModel):
    type: str
    source: str
    destination: Optional[str] = None
    reason: str
    confidence: float = 1.0

class OrganisationPlan(BaseModel):
    directories_to_create: List[str] = Field(default_factory=list)
    operations: List[PlannedOperation] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    untouched_files: List[str] = Field(default_factory=list)
    source_scope: Optional[str] = None

class ClassificationResult(BaseModel):
    category: str
    document_type: str
    confidence: float
    evidence: List[str] = Field(default_factory=list)

class GeneratedAsset(BaseModel):
    id: str
    vault_id: str
    asset_type: str
    title: str
    filename: str
    relative_path: str
    created_at: datetime
    source_chunks: List[str] = Field(default_factory=list)
    source_files: List[str] = Field(default_factory=list)
    source_scope: Optional[str] = None

class SearchResult(BaseModel):
    file_id: str
    relative_path: str
    filename: str
    snippet: str
    page: Optional[int] = None
    section: Optional[str] = None
    score: float

class Citation(BaseModel):
    file_path: str
    page: Optional[int] = None
    section: Optional[str] = None
    heading: Optional[str] = None
    chunk_text_preview: str

class RAGResponse(BaseModel):
    answer: str
    sources: List[Citation] = Field(default_factory=list)
    confidence: float = 1.0
