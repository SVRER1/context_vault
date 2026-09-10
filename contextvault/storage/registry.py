import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from contextvault.core.models import VaultInfo
from contextvault.storage.database import Database

class VaultRegistry:
    def __init__(self, db: Database):
        self.db = db

    def register_vault(self, path: Path, display_name: str) -> VaultInfo:
        vault_id = str(uuid.uuid4())
        now = datetime.now()
        vault_info = VaultInfo(
            id=vault_id,
            display_name=display_name,
            absolute_path=str(path.resolve()),
            created_at=now,
            last_opened_at=now
        )
        
        self.db.execute(
            """INSERT INTO vaults 
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
                vault_info.index_version
            )
        )
        self.db.conn.commit()
        return vault_info

    def get_vault(self, vault_id: str) -> Optional[VaultInfo]:
        row = self.db.fetch_one("SELECT * FROM vaults WHERE id = ?", (vault_id,))
        if not row:
            return None
        return VaultInfo(
            id=row['id'],
            display_name=row['display_name'],
            absolute_path=row['absolute_path'],
            created_at=datetime.fromisoformat(row['created_at']),
            last_opened_at=datetime.fromisoformat(row['last_opened_at']),
            last_indexed_at=datetime.fromisoformat(row['last_indexed_at']) if row['last_indexed_at'] else None,
            file_count=row['file_count'],
            chunk_count=row['chunk_count'],
            index_version=row['index_version']
        )

    def get_vault_by_path(self, path: Path) -> Optional[VaultInfo]:
        abs_path = str(path.resolve())
        row = self.db.fetch_one("SELECT * FROM vaults WHERE absolute_path = ?", (abs_path,))
        if not row:
            return None
        return VaultInfo(
            id=row['id'],
            display_name=row['display_name'],
            absolute_path=row['absolute_path'],
            created_at=datetime.fromisoformat(row['created_at']),
            last_opened_at=datetime.fromisoformat(row['last_opened_at']),
            last_indexed_at=datetime.fromisoformat(row['last_indexed_at']) if row['last_indexed_at'] else None,
            file_count=row['file_count'],
            chunk_count=row['chunk_count'],
            index_version=row['index_version']
        )

    def list_vaults(self) -> List[VaultInfo]:
        rows = self.db.fetch_all("SELECT * FROM vaults")
        vaults = []
        for row in rows:
            vaults.append(VaultInfo(
                id=row['id'],
                display_name=row['display_name'],
                absolute_path=row['absolute_path'],
                created_at=datetime.fromisoformat(row['created_at']),
                last_opened_at=datetime.fromisoformat(row['last_opened_at']),
                last_indexed_at=datetime.fromisoformat(row['last_indexed_at']) if row['last_indexed_at'] else None,
                file_count=row['file_count'],
                chunk_count=row['chunk_count'],
                index_version=row['index_version']
            ))
        return vaults

    def update_vault(self, vault_info: VaultInfo):
        self.db.execute(
            """UPDATE vaults 
               SET display_name=?, last_opened_at=?, last_indexed_at=?, file_count=?, chunk_count=?, index_version=? 
               WHERE id=?""",
            (
                vault_info.display_name,
                vault_info.last_opened_at.isoformat(),
                vault_info.last_indexed_at.isoformat() if vault_info.last_indexed_at else None,
                vault_info.file_count,
                vault_info.chunk_count,
                vault_info.index_version,
                vault_info.id
            )
        )
        self.db.conn.commit()

    def get_or_create_vault(self, path: Path) -> VaultInfo:
        vault = self.get_vault_by_path(path)
        if not vault:
            display_name = path.name
            vault = self.register_vault(path, display_name)
        else:
            vault.last_opened_at = datetime.now()
            self.update_vault(vault)
        return vault
