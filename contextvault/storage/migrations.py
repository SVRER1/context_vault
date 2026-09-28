"""Versioned, data-preserving SQLite schema migrations."""

from __future__ import annotations

import mimetypes
import sqlite3
from collections import defaultdict
from pathlib import Path

from contextvault.storage import schema


class DatabaseMigrationError(RuntimeError):
    """Raised when a database cannot be upgraded without ambiguity."""


class FTS5UnavailableError(DatabaseMigrationError):
    """Raised when this Python SQLite build does not provide FTS5."""


KNOWN_MIME_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".rst": "text/x-rst",
    ".log": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".json": "application/json",
    ".html": "text/html",
    ".htm": "text/html",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    return {str(row[0]) for row in rows}


def backup_unversioned_database(conn: sqlite3.Connection, db_path: Path) -> Path | None:
    """Create a consistent SQLite backup before upgrading existing data.

    A fresh empty database needs no backup. Existing backup files are kept and
    never overwritten, including after an interrupted migration.
    """
    if not _table_names(conn):
        return None

    backup_path = db_path.with_suffix(db_path.suffix + ".pre-v1.bak")
    if backup_path.exists():
        check = sqlite3.connect(str(backup_path))
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise DatabaseMigrationError(
                    f"Existing migration backup is not valid: {backup_path}"
                )
        finally:
            check.close()
        return backup_path

    destination = sqlite3.connect(str(backup_path))
    try:
        conn.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise DatabaseMigrationError(
                f"Could not verify pre-migration backup: {backup_path}"
            )
    except Exception:
        destination.close()
        try:
            backup_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    destination.close()
    return backup_path


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _add_missing_columns(
    conn: sqlite3.Connection, table: str, definitions: dict[str, str]
) -> None:
    existing = _columns(conn, table)
    for column, definition in definitions.items():
        if column not in existing:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')


def normalize_relative_path(value: str) -> str:
    """Normalize separators for storage without resolving user paths."""
    return str(value).replace("\\", "/")


def _backfill_file_metadata(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """SELECT id, vault_id, relative_path, filename, extension, size, mtime,
                  created_time, mime_family, parser, parse_status
           FROM files"""
    ).fetchall()
    word_counts: dict[str, int] = defaultdict(int)
    if "chunks" in _table_names(conn):
        for file_id, text in conn.execute("SELECT file_id, text FROM chunks"):
            word_counts[str(file_id)] += len(str(text or "").split())

    path_owners: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        file_id = str(row[0])
        vault_id = str(row[1])
        relative_path = normalize_relative_path(row[2] or "")
        filename = str(row[3] or Path(relative_path).name)
        extension = str(row[4] or Path(filename).suffix).lower()
        parent = relative_path.rpartition("/")[0]
        path_key = relative_path.casefold()
        path_owners[(vault_id, path_key)].append(relative_path)

        mime_type = (
            KNOWN_MIME_TYPES.get(extension)
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        mtime_ns = int(float(row[6] or 0) * 1_000_000_000)
        ctime_ns = int(float(row[7] or 0) * 1_000_000_000)
        old_status = str(row[10] or "pending").lower()
        extract_status = "ok" if old_status in {"parsed", "indexed", "ok"} else (
            "error" if old_status == "error" else "pending"
        )
        conn.execute(
            """UPDATE files SET relative_path = ?, filename = ?, extension = ?,
                      path_key = ?, parent_path = ?, mime_type = ?, mtime_ns = ?,
                      ctime_ns = ?, word_count = ?, extract_status = ?
               WHERE id = ?""",
            (
                relative_path,
                filename,
                extension,
                path_key,
                parent,
                mime_type,
                mtime_ns,
                ctime_ns,
                int(word_counts.get(file_id) or 0),
                extract_status,
                file_id,
            ),
        )

    duplicates = [
        (vault_id, key, paths)
        for (vault_id, key), paths in path_owners.items()
        if len(paths) > 1
    ]
    if duplicates:
        preview = "; ".join(
            f"{vault_id}: {', '.join(paths)}" for vault_id, _, paths in duplicates[:10]
        )
        raise DatabaseMigrationError(
            "Cannot create case-insensitive unique vault paths because legacy rows "
            f"collide after normalization. Resolve these paths and retry: {preview}"
        )


def _create_fts5(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("DROP TABLE IF EXISTS chunks_fts")
        conn.execute(schema.CHUNKS_FTS5_SCHEMA)
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "fts5" in message or "no such module" in message:
            raise FTS5UnavailableError(
                "Context Vault requires SQLite FTS5 for deterministic indexed search. "
                "Install a Python build linked with FTS5, then retry the migration."
            ) from exc
        raise

    conn.execute(
        """INSERT INTO chunks_fts
           (id, file_id, vault_id, relative_path, filename, text, heading, section)
           SELECT c.id, c.file_id, c.vault_id, c.relative_path,
                  COALESCE(f.filename, ''), c.text, COALESCE(c.heading, ''),
                  COALESCE(c.section, '')
           FROM chunks AS c LEFT JOIN files AS f ON f.id = c.file_id"""
    )


def _migrate_v1(conn: sqlite3.Connection) -> None:
    _add_missing_columns(
        conn, "generated_assets", {"source_scope": "TEXT"}
    )
    _add_missing_columns(conn, "files", schema.MIGRATION_1_FILE_COLUMNS)
    _add_missing_columns(conn, "chunks", schema.MIGRATION_1_CHUNK_COLUMNS)
    _backfill_file_metadata(conn)

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_files_vault_path_key "
        "ON files(vault_id, path_key)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_files_vault_mtime_ns "
        "ON files(vault_id, mtime_ns)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_files_vault_sha256 "
        "ON files(vault_id, sha256)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_files_vault_parent "
        "ON files(vault_id, parent_path)"
    )
    for statement in schema.FILE_TAGS_SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)
    for statement in schema.INDEX_RUNS_SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)

    _create_fts5(conn)
    conn.execute("PRAGMA user_version = 1")


def _migrate_v2(conn: sqlite3.Connection) -> None:
    for statement in schema.MIGRATION_2_OPERATION_PLANS_SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)
    conn.execute("PRAGMA user_version = 2")


def _migrate_v3(conn: sqlite3.Connection) -> None:
    for statement in schema.MIGRATION_3_JOURNAL_SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)
    conn.execute("PRAGMA user_version = 3")


def _migrate_v4(conn: sqlite3.Connection) -> None:
    _add_missing_columns(conn, "operation_items_v3", {"result_file_id": "TEXT"})
    conn.execute("PRAGMA user_version = 4")


def _migrate_v5(conn: sqlite3.Connection) -> None:
    _add_missing_columns(conn, "operation_items_v3", {
        "undo_of_item_id": "TEXT",
        "undo_status": "TEXT NOT NULL DEFAULT 'none'",
        "undo_batch_id": "TEXT",
    })
    conn.execute("PRAGMA user_version = 5")


def migrate(conn: sqlite3.Connection) -> None:
    """Upgrade the unversioned legacy database to the current schema."""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version > schema.CURRENT_SCHEMA_VERSION:
        raise DatabaseMigrationError(
            f"Database schema version {version} is newer than this application "
            f"supports ({schema.CURRENT_SCHEMA_VERSION})."
        )

    if version == 0:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_v1(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        version = 1

    if version == 1:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_v2(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        version = 2

    if version == 2:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_v3(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        version = 3

    if version == 3:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_v4(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        version = 4

    if version == 4:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_v5(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        version = 5

    if version == schema.CURRENT_SCHEMA_VERSION:
        try:
            conn.execute("SELECT count(*) FROM chunks_fts").fetchone()
        except sqlite3.OperationalError as exc:
            raise FTS5UnavailableError(
                "The current Context Vault database is missing a working FTS5 "
                "index. Restore its backup or run the database repair command."
            ) from exc
