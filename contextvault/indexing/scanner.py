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
        self.event_bus.emit(Event(type=EventType.SCAN_STARTED, data={"vault_id": self.vault.vault_id}))
        records = []
        scanned_count = 0
        
        for root, dirs, files in os.walk(self.vault.root_path):
            root_path = Path(root)
            dirs[:] = [d for d in dirs if not self._should_ignore(root_path / d)]
            
            for file_name in files:
                file_path = root_path / file_name
                if self._should_ignore(file_path):
                    continue
                    
                try:
                    record = self._get_file_info(file_path)
                    records.append(record)
                    scanned_count += 1
                    
                                                               
                    existing = self.db.get_file_by_path(self.vault.vault_id, record.relative_path)
                    if existing:
                                                                     
                        record_id = existing["id"]
                        record.id = record_id
                        self.db.execute('''
                            UPDATE files SET
                                filename = ?, extension = ?, size = ?, mtime = ?,
                                created_time = ?, sha256 = ?, mime_family = ?
                            WHERE id = ?
                        ''', (
                            record.filename, record.extension, record.size, record.mtime,
                            record.created_time, record.sha256, record.mime_family, record_id
                        ))
                    else:
                        self.db.execute('''
                            INSERT INTO files (
                                id, vault_id, relative_path, filename, extension,
                                size, mtime, created_time, sha256, mime_family,
                                parser, parse_status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            record.id, record.vault_id, record.relative_path, record.filename, record.extension,
                            record.size, record.mtime, record.created_time, record.sha256, record.mime_family,
                            record.parser, record.parse_status
                        ))
                    
                    if scanned_count % 100 == 0:
                        self.db.conn.commit()
                        self.event_bus.emit(Event(
                            type=EventType.SCAN_PROGRESS, 
                            data={"vault_id": self.vault.vault_id, "scanned": scanned_count}
                        ))
                except Exception as e:
                    self.event_bus.emit(Event(
                        type=EventType.ERROR, 
                        data={"vault_id": self.vault.vault_id, "file": str(file_path), "error": str(e)}
                    ))
                    
        self.db.conn.commit()
        self.event_bus.emit(Event(
            type=EventType.SCAN_COMPLETE, 
            data={"vault_id": self.vault.vault_id, "total": scanned_count}
        ))
        return records
