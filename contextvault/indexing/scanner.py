import os
import uuid
from pathlib import Path
from typing import List
from datetime import datetime

from contextvault.core.vault import Vault
from contextvault.storage.database import Database
from contextvault.core.models import FileRecord
from contextvault.indexing.fingerprint import compute_sha256
from contextvault.core.events import EventBus, Event, EventType
from contextvault.core.config import get_config
from contextvault.retrieval.filesystem_policy import is_ignored_source_path

class FileScanner:
    def __init__(self, vault: Vault, db: Database, event_bus: EventBus = None):
        self.vault = vault
        self.db = db
        self.event_bus = event_bus or EventBus()
        self.config = get_config()

    def _should_ignore(self, path: Path) -> bool:
        """Skip shared implementation/runtime/output source paths."""
        return is_ignored_source_path(path, self.config.generated_output_folder)

    def _detect_mime_family(self, ext: str) -> str:
        ext = ext.lower()
        if ext in {".txt", ".md", ".rst", ".log", ".pdf", ".docx", ".pptx", ".csv", ".xlsx"}:
            return "document"
        elif ext in {".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".rs", ".go", ".cs", ".sql", ".sh", ".ps1"}:
            return "code"
        elif ext in {".json", ".xml", ".yaml", ".yml", ".toml"}:
            return "data"
        elif ext in {".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp"}:
            return "image"
        elif ext in {".zip", ".tar", ".gz", ".rar", ".7z"}:
            return "archive"
        return "other"

    def _get_file_info(self, path: Path) -> FileRecord:
        """Safe stat + metadata extraction."""
        stat = path.stat()
        rel_path = self.vault.relative_path(path)
        ext = path.suffix
        
        return FileRecord(
            id=str(uuid.uuid4()),
            vault_id=self.vault.vault_id,
            relative_path=rel_path,
            filename=path.name,
            extension=ext,
            size=stat.st_size,
            mtime=stat.st_mtime,
            created_time=stat.st_ctime,
            sha256=compute_sha256(path),
            mime_family=self._detect_mime_family(ext),
            parser=None,
            parse_status="pending"
        )

    def scan(self) -> List[FileRecord]:
        """Compatibility entry point backed by the incremental reconciler."""
        from contextvault.indexing.index_service import IndexService

        self.event_bus.emit(Event(type=EventType.SCAN_STARTED, data={"vault_id": self.vault.vault_id}))
        IndexService(self.vault, self.db, self.config).reconcile()
        records = []
        for row in self.db.get_all_files(self.vault.vault_id):
            try:
                records.append(FileRecord(
                    id=row["id"], vault_id=row["vault_id"], relative_path=row["relative_path"],
                    filename=row["filename"], extension=row["extension"], size=row["size"],
                    mtime=row["mtime"], created_time=row["created_time"], sha256=row["sha256"],
                    mime_family=row["mime_family"], parser=row.get("parser"),
                    parse_status=row.get("parse_status", "pending"), indexed_at=row.get("indexed_at"),
                    path_key=row.get("path_key"), parent_path=row.get("parent_path"),
                    mime_type=row.get("mime_type"), mtime_ns=row.get("mtime_ns"),
                    ctime_ns=row.get("ctime_ns"), word_count=row.get("word_count", 0),
                    document_title=row.get("document_title"),
                    document_metadata_json=row.get("document_metadata_json", "{}"),
                    extract_status=row.get("extract_status", "pending"),
                    extract_error=row.get("extract_error"), last_seen_scan=row.get("last_seen_scan"),
                ))
            except Exception as exc:
                self.event_bus.emit(Event(type=EventType.ERROR, data={"vault_id": self.vault.vault_id, "error": str(exc)}))
        self.event_bus.emit(Event(type=EventType.SCAN_COMPLETE, data={"vault_id": self.vault.vault_id, "total": len(records)}))
        return records
