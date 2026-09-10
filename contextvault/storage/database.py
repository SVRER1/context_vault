import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
from contextvault.storage.schema import ALL_SCHEMAS

class Database:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._init_connection()

    def _init_connection(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")

    def initialize(self):
        """Creates tables from schema."""
        for schema_sql in ALL_SCHEMAS:
            self.conn.executescript(schema_sql)
                                                                                 
        try:
            self.conn.execute("ALTER TABLE generated_assets ADD COLUMN source_scope TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
        self.conn.commit()

    @contextmanager
    def transaction(self):
        """Context manager for transactions."""
        try:
            yield self
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params_list: List[tuple]):
        self.conn.executemany(sql, params_list)

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        cursor = self.conn.execute(sql, params)
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

    def fetch_all(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single chunk by ID."""
        return self.fetch_one("SELECT * FROM chunks WHERE id = ?", (chunk_id,))

    def get_chunks_by_file_id(self, file_id: str) -> List[Dict[str, Any]]:
        """Fetch all chunks for a file."""
        return self.fetch_all("SELECT * FROM chunks WHERE file_id = ? ORDER BY chunk_index", (file_id,))

    def get_chunks_by_vault(self, vault_id: str) -> List[Dict[str, Any]]:
        """Fetch all chunks for a vault."""
        return self.fetch_all("SELECT * FROM chunks WHERE vault_id = ? ORDER BY relative_path, chunk_index", (vault_id,))

    def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single file by ID."""
        return self.fetch_one("SELECT * FROM files WHERE id = ?", (file_id,))

    def get_file_by_path(self, vault_id: str, relative_path: str) -> Optional[Dict[str, Any]]:
        """Fetch a single file by relative path."""
        return self.fetch_one("SELECT * FROM files WHERE vault_id = ? AND relative_path = ?", (vault_id, relative_path))

    def get_all_files(self, vault_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all files, optionally filtered by vault."""
        if vault_id:
            return self.fetch_all("SELECT * FROM files WHERE vault_id = ? ORDER BY relative_path", (vault_id,))
        return self.fetch_all("SELECT * FROM files ORDER BY relative_path")

    def close(self):
        self.conn.close()
