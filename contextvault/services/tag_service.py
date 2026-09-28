"""Vault-scoped tag operations over stable file IDs and canonical paths."""

from __future__ import annotations

from contextvault.core.config import get_config
from contextvault.core.vault import Vault
from contextvault.storage.database import Database
from contextvault.storage.index_repository import IndexRepository
from contextvault.indexing.index_service import IndexService


class TagService:
    def __init__(self, vault: Vault, db: Database, index_service: IndexService | None = None):
        self.vault = vault
        self.db = db
        self.repository = IndexRepository(db)
        self.index_service = index_service or IndexService(vault, db, get_config())

    def resolve_file_id(self, target: str) -> str:
        self.index_service.reconcile()
        by_id = self.db.fetch_one(
            "SELECT id FROM files WHERE vault_id=? AND id=?", (self.vault.vault_id, target)
        )
        if by_id:
            return by_id["id"]
        relative = target.replace("\\", "/").strip("/")
        row = self.db.fetch_one(
            "SELECT id FROM files WHERE vault_id=? AND path_key=?",
            (self.vault.vault_id, relative.casefold()),
        )
        if not row:
            raise KeyError(f"Indexed file not found: {target}")
        return row["id"]

    def add(self, target: str, tag: str) -> list[str]:
        file_id = self.resolve_file_id(target)
        self.repository.add_tag(file_id, tag)
        self.db.conn.commit()
        return self.repository.get_tags(file_id)

    def remove(self, target: str, tag: str) -> list[str]:
        file_id = self.resolve_file_id(target)
        self.repository.remove_tag(file_id, tag)
        self.db.conn.commit()
        return self.repository.get_tags(file_id)

    def list(self, target: str) -> list[str]:
        return self.repository.get_tags(self.resolve_file_id(target))
