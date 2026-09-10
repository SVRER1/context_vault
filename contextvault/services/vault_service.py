"""Vault service for managing context vaults.

Handles vault lifecycle: opening, scanning, indexing, and status reporting.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from contextvault.core.config import AppConfig
from contextvault.core.models import VaultInfo, FileRecord
from contextvault.core.vault import Vault
from contextvault.storage.database import Database
from contextvault.storage.registry import VaultRegistry

logger = logging.getLogger(__name__)


class VaultService:
    """Service for managing context vaults."""

    def __init__(self, config: AppConfig, app_db: Database):
        self.config = config
        self.app_db = app_db
        self.registry = VaultRegistry(app_db)
        self._active_vault: Vault | None = None

    def open_vault(self, path: str | Path) -> Vault:
        """Open or create a vault at the given path.

        Steps:
        1. Resolve canonical path
        2. Validate it's a directory
        3. Get or create vault registry record
        4. Create vault data directory
        5. Initialize vault database
        6. Create and return Vault object
        """
        resolved_path = Path(path).resolve()
        if not resolved_path.exists():
            raise ValueError(f"Path does not exist: {resolved_path}")
        if not resolved_path.is_dir():
            raise ValueError(f"Path is not a directory: {resolved_path}")

                                         
        vault_info = self.registry.get_or_create_vault(resolved_path)

                                     
        vault_data_dir = self.config.vault_data_dir(vault_info.id)
        vault_data_dir.mkdir(parents=True, exist_ok=True)
        (vault_data_dir / "cache").mkdir(exist_ok=True)

                                            
        vault_db = Database(vault_data_dir / "index.db")
        vault_db.initialize()
        vault_db.execute(
            """INSERT OR REPLACE INTO vaults 
               (id, display_name, absolute_path, created_at, last_opened_at, file_count, chunk_count, index_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                vault_info.id,
                vault_info.display_name,
                vault_info.absolute_path,
                vault_info.created_at.isoformat(),
                vault_info.last_opened_at.isoformat(),
                vault_info.file_count,
                vault_info.chunk_count,
                vault_info.index_version,
            ),
        )
        vault_db.conn.commit()

                             
        vault = Vault(vault_info)
        self._active_vault = vault

        logger.info(f"Opened vault: {vault.display_name} at {vault.root_path}")
        return vault

    def get_vault_db(self, vault: Vault) -> Database:
        """Get the database for a specific vault."""
        vault_data_dir = self.config.vault_data_dir(vault.vault_id)
        db = Database(vault_data_dir / "index.db")
        db.initialize()
        db.execute(
            """INSERT OR IGNORE INTO vaults 
               (id, display_name, absolute_path, created_at, last_opened_at, file_count, chunk_count, index_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                vault.vault_id,
                vault.display_name,
                str(vault.root_path),
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                0,
                0,
                1,
            ),
        )
        db.conn.commit()
        return db

    def list_vaults(self) -> list[VaultInfo]:
        """List all registered vaults."""
        return self.registry.list_vaults()

    def get_active_vault(self) -> Vault | None:
        """Get the currently active vault."""
        return self._active_vault

    def scan_vault(self, vault: Vault, db: Database) -> list[FileRecord]:
        """Scan the vault directory for files.

        Args:
            vault: The vault to scan.
            db: The vault database.

        Returns:
            List of discovered FileRecord objects.
        """
        from contextvault.indexing.scanner import FileScanner

        scanner = FileScanner(vault, db)
        files = scanner.scan()

                                             
        vault_info = self.registry.get_vault(vault.vault_id)
        if vault_info:
            vault_info.file_count = len(files)
            self.registry.update_vault(vault_info)

        return files

    def index_vault(
        self,
        vault: Vault,
        db: Database,
        progress_callback=None,
        ocr_client=None,
    ) -> dict[str, Any]:
        """Optional parse/cache pass; retrieval itself reads the filesystem live.

        Args:
            vault: The vault to index.
            db: The vault database.
            progress_callback: Optional callback(current, total, message).

        Returns:
            Dict with indexing statistics.
        """
        from contextvault.indexing.scanner import FileScanner
        from contextvault.indexing.chunker import DocumentChunker
        from contextvault.parsers.registry import create_default_registry

        stats = {
            "scanned": 0,
            "parsed": 0,
            "chunks_created": 0,
            "errors": 0,
            "skipped": 0,
        }

                 
        scanner = FileScanner(vault, db)
        files = scanner.scan()
        stats["scanned"] = len(files)

                                                                              
                                                                             
        current_ids = [file_record.id for file_record in files]
        if current_ids:
            placeholders = ",".join("?" for _ in current_ids)
            db.execute(
                f"DELETE FROM files WHERE vault_id = ? AND id NOT IN ({placeholders})",
                (vault.vault_id, *current_ids),
            )
        else:
            db.execute("DELETE FROM files WHERE vault_id = ?", (vault.vault_id,))
        db.execute("DELETE FROM chunks WHERE vault_id = ?", (vault.vault_id,))
        try:
            db.execute("DELETE FROM chunks_fts WHERE vault_id = ?", (vault.vault_id,))
        except Exception:
                                                                         
            pass
        db.conn.commit()
        if progress_callback:
            progress_callback(0, len(files), "Scanning complete")

                                      
        parser_registry = create_default_registry(ocr_client=ocr_client)
        chunker = DocumentChunker()

        all_chunks = []

        for i, file_record in enumerate(files):
            try:
                if progress_callback:
                    progress_callback(i, len(files), f"Processing {file_record.filename}")

                                                           
                parser = parser_registry.get_parser(file_record.extension)
                if parser is None:
                    stats["skipped"] += 1
                    continue

                       
                file_path = vault.root_path / file_record.relative_path
                parsed_doc = parser.parse(file_path, file_record.id)
                stats["parsed"] += 1

                                           
                db.execute(
                    "UPDATE files SET parse_status = 'parsed', parser = ? WHERE id = ?",
                    (type(parser).__name__, file_record.id),
                )

                       
                chunks = chunker.chunk(
                    parsed_doc,
                    vault_id=vault.vault_id,
                    relative_path=file_record.relative_path,
                    target_tokens=self.config.chunk_size_tokens,
                    overlap_tokens=self.config.chunk_overlap_tokens,
                )
                stats["chunks_created"] += len(chunks)

                                    
                for chunk in chunks:
                    chunk_data = chunk.model_dump()
                    chunk_data["vault_id"] = vault.vault_id
                    chunk_data["relative_path"] = file_record.relative_path
                    db.execute(
                        """INSERT OR REPLACE INTO chunks
                           (id, file_id, vault_id, relative_path, chunk_index, text, page, section, heading)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            chunk.id,
                            chunk.file_id,
                            vault.vault_id,
                            file_record.relative_path,
                            chunk.chunk_index,
                            chunk.text,
                            chunk.page,
                            chunk.section,
                            chunk.heading,
                        ),
                    )
                    all_chunks.append(chunk)

            except Exception as e:
                logger.error(f"Error indexing {file_record.filename}: {e}")
                stats["errors"] += 1
                db.execute(
                    "UPDATE files SET parse_status = 'error' WHERE id = ?",
                    (file_record.id,),
                )

        db.conn.commit()

                                                                             
                                                                        
        try:
            from contextvault.retrieval.lexical import LexicalSearch
            lexical = LexicalSearch(db)
            lexical.index_chunks(all_chunks, vault_id=vault.vault_id)
        except Exception as e:
            logger.warning(f"Could not build lexical index: {e}")

                               
        vault_info = self.registry.get_vault(vault.vault_id)
        if vault_info:
            vault_info.file_count = stats["scanned"]
            vault_info.chunk_count = stats["chunks_created"]
            vault_info.last_indexed_at = datetime.now()
            self.registry.update_vault(vault_info)

        if progress_callback:
            progress_callback(len(files), len(files), "Indexing complete")

        stats["parsed_files"] = stats["parsed"]
        stats["total_chunks"] = stats["chunks_created"]
        return stats

    def get_vault_status(self, vault: Vault) -> dict[str, Any]:
        """Get current status for a vault."""
        vault_info = self.registry.get_vault(vault.vault_id)
        if not vault_info:
            return {"status": "unknown"}

        return {
            "id": vault.vault_id,
            "display_name": vault.display_name,
            "path": str(vault.root_path),
            "file_count": vault_info.file_count,
            "chunk_count": vault_info.chunk_count,
            "last_indexed_at": vault_info.last_indexed_at.isoformat() if vault_info.last_indexed_at else None,
            "index_version": vault_info.index_version,
            "status": "ready",
        }
