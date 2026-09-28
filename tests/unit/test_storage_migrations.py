import sqlite3
from datetime import datetime, timezone

import pytest

from contextvault.core.models import ChunkRecord
from contextvault.storage.database import Database
from contextvault.storage.index_repository import IndexRepository
from contextvault.storage.migrations import (
    DatabaseMigrationError,
    FTS5UnavailableError,
    _create_fts5,
)


def _make_legacy_database(path, *, duplicate_case_path=False, vault_root="/tmp/vault"):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE vaults (
            id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            absolute_path TEXT NOT NULL, created_at TIMESTAMP NOT NULL,
            last_opened_at TIMESTAMP NOT NULL, last_indexed_at TIMESTAMP,
            file_count INTEGER DEFAULT 0, chunk_count INTEGER DEFAULT 0,
            index_version INTEGER DEFAULT 1
        );
        CREATE TABLE files (
            id TEXT PRIMARY KEY, vault_id TEXT NOT NULL, relative_path TEXT NOT NULL,
            filename TEXT NOT NULL, extension TEXT NOT NULL, size INTEGER NOT NULL,
            mtime REAL NOT NULL, created_time REAL NOT NULL, sha256 TEXT NOT NULL,
            mime_family TEXT NOT NULL, parser TEXT, parse_status TEXT DEFAULT 'pending',
            indexed_at TIMESTAMP, FOREIGN KEY(vault_id) REFERENCES vaults(id)
        );
        CREATE TABLE chunks (
            id TEXT PRIMARY KEY, file_id TEXT NOT NULL, vault_id TEXT NOT NULL,
            relative_path TEXT NOT NULL, chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL, page INTEGER, section TEXT, heading TEXT,
            FOREIGN KEY(file_id) REFERENCES files(id),
            FOREIGN KEY(vault_id) REFERENCES vaults(id)
        );
        CREATE TABLE operations (
            operation_id TEXT PRIMARY KEY, timestamp TIMESTAMP NOT NULL,
            vault_id TEXT NOT NULL, operation_type TEXT NOT NULL,
            source_path TEXT NOT NULL, destination_path TEXT, hash_before TEXT,
            hash_after TEXT, status TEXT NOT NULL, reason TEXT,
            user_approved BOOLEAN DEFAULT 0, batch_id TEXT,
            undo_status TEXT DEFAULT 'none',
            FOREIGN KEY(vault_id) REFERENCES vaults(id)
        );
        CREATE TABLE generated_assets (
            id TEXT PRIMARY KEY, vault_id TEXT NOT NULL, asset_type TEXT NOT NULL,
            title TEXT NOT NULL, filename TEXT NOT NULL, relative_path TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL, source_chunks TEXT, source_files TEXT,
            FOREIGN KEY(vault_id) REFERENCES vaults(id)
        );
        """
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO vaults(id,display_name,absolute_path,created_at,last_opened_at) "
        "VALUES('v1','Vault',?,?,?)",
        (vault_root, now, now),
    )
    conn.execute(
        """INSERT INTO files
           (id,vault_id,relative_path,filename,extension,size,mtime,created_time,
            sha256,mime_family,parser,parse_status)
           VALUES('f1','v1','Notes\\Topic.MD','Topic.MD','.MD',51,123.5,100.25,
                  'abc','document','PlainTextParser','parsed')"""
    )
    conn.execute(
        """INSERT INTO chunks
           (id,file_id,vault_id,relative_path,chunk_index,text,page,section,heading)
           VALUES('c1','f1','v1','Notes\\Topic.MD',0,
                  'needle in the legacy chunk',2,'body','Heading')"""
    )
    conn.execute(
        """INSERT INTO operations
           (operation_id,timestamp,vault_id,operation_type,source_path,status)
           VALUES('o1',?,'v1','move','old.md','completed')""",
        (now,),
    )
    conn.execute(
        """INSERT INTO generated_assets
           (id,vault_id,asset_type,title,filename,relative_path,created_at)
           VALUES('g1','v1','summary','Summary','summary.md','Generated/summary.md',?)""",
        (now,),
    )
    if duplicate_case_path:
        conn.execute(
            """INSERT INTO files
               (id,vault_id,relative_path,filename,extension,size,mtime,created_time,
                sha256,mime_family)
               VALUES('f2','v1','notes/topic.md','topic.md','.md',1,1,1,'def','document')"""
        )
    conn.commit()
    conn.close()


def test_v1_migration_preserves_rows_rebuilds_fts_and_is_idempotent(tmp_path):
    db_path = tmp_path / "index.db"
    vault_root = tmp_path / "vault"
    (vault_root / "Notes").mkdir(parents=True)
    (vault_root / "Notes" / "Topic.MD").write_text("needle in the legacy chunk", encoding="utf-8")
    _make_legacy_database(db_path, vault_root=str(vault_root))

    db = Database(db_path)
    db.initialize()
    backup_path = tmp_path / "index.db.pre-v1.bak"

    assert backup_path.exists()
    backup = sqlite3.connect(backup_path)
    assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert "path_key" not in {row[1] for row in backup.execute("PRAGMA table_info(files)")}
    backup.close()

    assert db.execute("PRAGMA user_version").fetchone()[0] == 5
    assert db.fetch_one("SELECT name FROM sqlite_master WHERE name='operation_items_v3'")
    assert db.fetch_one("SELECT name FROM sqlite_master WHERE type='table' AND name='file_operation_plans'")
    file_row = db.get_file_by_id("f1")
    assert file_row["relative_path"] == "Notes/Topic.MD"
    assert file_row["path_key"] == "notes/topic.md"
    assert file_row["parent_path"] == "Notes"
    assert file_row["mime_type"]
    assert file_row["mtime_ns"] == 123_500_000_000
    assert file_row["word_count"] == 5
    assert file_row["extract_status"] == "ok"
    assert db.get_chunk_by_id("c1")["heading"] == "Heading"
    assert db.fetch_one("SELECT operation_id FROM operations WHERE operation_id='o1'")
    assert db.fetch_one("SELECT source_scope FROM generated_assets WHERE id='g1'")["source_scope"] is None
    fts = db.fetch_one("SELECT id, filename FROM chunks_fts WHERE chunks_fts MATCH 'needle'")
    assert fts == {"id": "c1", "filename": "Topic.MD"}

    from contextvault.core.models import VaultInfo
    from contextvault.core.vault import Vault
    from contextvault.retrieval.search_models import SearchRequest
    from contextvault.retrieval.search_service import SearchService
    legacy_vault = Vault(VaultInfo(
        id="v1", display_name="Vault", absolute_path=str(vault_root),
        created_at=datetime.now(timezone.utc), last_opened_at=datetime.now(timezone.utc),
    ))
    migrated_search = SearchService(legacy_vault, db).search(SearchRequest(
        vault_id="v1", query="needle", freshness_policy="cached",
    ))
    assert [hit.relative_path for hit in migrated_search.hits] == ["Notes/Topic.MD"]

    repo = IndexRepository(db)
    with db.transaction():
        repo.add_tag("f1", "Course Work")
        repo.add_tag("f1", "course work")
        run_id = repo.start_index_run("v1", "Notes")
        repo.finish_index_run(run_id, status="complete", discovered=1, unchanged=1)
        repo.replace_file_chunks(
            "f1",
            [ChunkRecord(
                id="c2", file_id="f1", vault_id="v1", relative_path="Notes/Topic.MD",
                chunk_index=0, text="updated passage", line_start=4, line_end=5,
                metadata_json='{"kind":"heading"}',
            )],
            vault_id="v1",
            relative_path="Notes/Topic.MD",
            filename="Topic.MD",
        )
    assert repo.get_tags("f1") == ["course work"]
    assert db.fetch_one("SELECT line_start,line_end FROM chunks WHERE id='c2'") == {
        "line_start": 4, "line_end": 5
    }
    assert db.fetch_one("SELECT id FROM chunks_fts WHERE chunks_fts MATCH 'updated'")["id"] == "c2"
    assert db.fetch_one("SELECT status FROM index_runs WHERE run_id=?", (run_id,))["status"] == "complete"

    db.close()
    upgraded = Database(db_path)
    upgraded.initialize()
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == 5
    assert upgraded.fetch_one("SELECT count(*) AS n FROM operations")["n"] == 1
    assert upgraded.fetch_one("SELECT count(*) AS n FROM chunks")["n"] == 1
    assert upgraded.fetch_one("PRAGMA integrity_check")["integrity_check"] == "ok"
    assert upgraded.fetch_all("PRAGMA foreign_key_check") == []
    upgraded.close()


def test_casefold_path_collision_fails_without_dropping_legacy_rows(tmp_path):
    db_path = tmp_path / "index.db"
    _make_legacy_database(db_path, duplicate_case_path=True)
    db = Database(db_path)

    with pytest.raises(DatabaseMigrationError, match="collide after normalization"):
        db.initialize()

    assert db.execute("PRAGMA user_version").fetchone()[0] == 0
    assert db.fetch_one("SELECT count(*) AS n FROM files")["n"] == 2
    assert "path_key" not in {row[1] for row in db.execute("PRAGMA table_info(files)")}
    assert (tmp_path / "index.db.pre-v1.bak").exists()
    db.close()


def test_fts5_unavailable_error_is_explicit():
    class MissingFTS5Connection:
        def execute(self, statement):
            if statement.startswith("DROP TABLE"):
                return None
            raise sqlite3.OperationalError("no such module: fts5")

    with pytest.raises(FTS5UnavailableError, match="requires SQLite FTS5"):
        _create_fts5(MissingFTS5Connection())
