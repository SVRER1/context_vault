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
        force: bool = False,
    ) -> dict[str, Any]:
        """Optional parse/cache pass; retrieval itself reads the filesystem live.

        Args:
            vault: The vault to index.
            db: The vault database.
            progress_callback: Optional callback(current, total, message).

        Returns:
            Dict with indexing statistics.
        """
        
        
        from contextvault.indexing.index_service import IndexService

        result = IndexService(vault, db, self.config).reconcile(
            force=force, progress_callback=progress_callback
        )
        chunks = db.fetch_one("SELECT COUNT(*) AS count FROM chunks WHERE vault_id = ?", (vault.vault_id,))["count"]
        parsed = db.fetch_one(
            "SELECT COUNT(*) AS count FROM files WHERE vault_id = ? AND extract_status IN ('ok', 'truncated')",
            (vault.vault_id,),
        )["count"]
        result.update(
            scanned=result["discovered"],
            parsed=parsed,
            parsed_files=parsed,
            errors=result["failed"],
            skipped=db.fetch_one(
                "SELECT COUNT(*) AS count FROM files WHERE vault_id = ? AND extract_status = 'unsupported'",
                (vault.vault_id,),
            )["count"],
            chunks_created=chunks,
            total_chunks=chunks,
        )
        return result

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
