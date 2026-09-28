"""Parameterized persistence helpers for the local content index."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from contextvault.core.models import ChunkRecord, FileRecord
from contextvault.storage.database import Database
from contextvault.storage.migrations import normalize_relative_path


class IndexRepository:
    """Read and update file metadata, passages, tags, and FTS rows.

    Methods deliberately do not commit. Callers can update a file row, its
    chunks, and the matching FTS rows in one ``Database.transaction``.
    """

    def __init__(self, db: Database):
        self.db = db

    def upsert_file(self, record: FileRecord, scan_id: str | None = None) -> None:
        relative_path = normalize_relative_path(record.relative_path)
        path_key = record.path_key or relative_path.casefold()
        parent_path = record.parent_path
        if parent_path is None:
            parent_path = relative_path.rpartition("/")[0]
        values = (
            record.id,
            record.vault_id,
            relative_path,
            path_key,
            parent_path,
            record.filename,
            record.extension.lower(),
            record.mime_type,
            record.size,
            record.mtime,
            record.mtime_ns,
            record.created_time,
            record.ctime_ns,
            record.sha256,
            record.mime_family,
            record.parser,
            record.parse_status,
            record.indexed_at.isoformat() if record.indexed_at else None,
            record.word_count,
            record.document_title,
            record.document_metadata_json,
            record.extract_status,
            record.extract_error,
            scan_id or record.last_seen_scan,
        )
        self.db.execute(
            """INSERT INTO files (
                   id, vault_id, relative_path, path_key, parent_path, filename,
                   extension, mime_type, size, mtime, mtime_ns, created_time,
                   ctime_ns, sha256, mime_family, parser, parse_status, indexed_at,
                   word_count, document_title, document_metadata_json,
                   extract_status, extract_error, last_seen_scan
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   vault_id=excluded.vault_id,
                   relative_path=excluded.relative_path,
                   path_key=excluded.path_key,
                   parent_path=excluded.parent_path,
                   filename=excluded.filename,
                   extension=excluded.extension,
                   mime_type=excluded.mime_type,
                   size=excluded.size,
                   mtime=excluded.mtime,
                   mtime_ns=excluded.mtime_ns,
                   created_time=excluded.created_time,
                   ctime_ns=excluded.ctime_ns,
                   sha256=excluded.sha256,
                   mime_family=excluded.mime_family,
                   parser=excluded.parser,
                   parse_status=excluded.parse_status,
                   indexed_at=excluded.indexed_at,
                   word_count=excluded.word_count,
                   document_title=excluded.document_title,
                   document_metadata_json=excluded.document_metadata_json,
                   extract_status=excluded.extract_status,
                   extract_error=excluded.extract_error,
                   last_seen_scan=excluded.last_seen_scan""",
            values,
        )

    def get_file_by_path(self, vault_id: str, relative_path: str) -> dict[str, Any] | None:
        key = normalize_relative_path(relative_path).casefold()
        return self.db.fetch_one(
            "SELECT * FROM files WHERE vault_id = ? AND path_key = ?",
            (vault_id, key),
        )

    def set_extraction_result(
        self,
        file_id: str,
        *,
        status: str,
        parser: str | None,
        word_count: int = 0,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
        indexed_at: datetime | None = None,
    ) -> None:
        if status not in {"pending", "ok", "empty", "unsupported", "truncated", "error"}:
            raise ValueError(f"Unsupported extraction status: {status}")
        self.db.execute(
            """UPDATE files SET parser=?, parse_status=?, extract_status=?,
                      extract_error=?, word_count=?, document_title=?,
                      document_metadata_json=?, indexed_at=? WHERE id=?""",
            (
                parser,
                "parsed" if status in {"ok", "empty"} else status,
                status,
                error,
                max(0, int(word_count)),
                title,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                (indexed_at or datetime.now(timezone.utc)).isoformat(),
                file_id,
            ),
        )

    def replace_file_chunks(
        self,
        file_id: str,
        chunks: Iterable[ChunkRecord | dict[str, Any]],
        *,
        vault_id: str,
        relative_path: str,
        filename: str | None = None,
    ) -> None:
        relative_path = normalize_relative_path(relative_path)
        if filename is None:
            row = self.db.get_file_by_id(file_id)
            filename = row["filename"] if row else ""
        self.db.execute("DELETE FROM chunks_fts WHERE file_id = ?", (file_id,))
        self.db.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

        for chunk in chunks:
            value = chunk.model_dump() if isinstance(chunk, ChunkRecord) else dict(chunk)
            chunk_id = value.get("id") or str(uuid.uuid4())
            heading = value.get("heading") or ""
            section = value.get("section") or value.get("sheet") or ""
            text = str(value.get("text", value.get("content", "")))
            metadata_json = value.get("metadata_json", "{}")
            if not isinstance(metadata_json, str):
                metadata_json = json.dumps(metadata_json, ensure_ascii=False, sort_keys=True)
            self.db.execute(
                """INSERT INTO chunks (
                       id, file_id, vault_id, relative_path, chunk_index, text,
                       page, section, heading, line_start, line_end, slide,
                       sheet, cell_range, char_start, char_end, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk_id,
                    file_id,
                    vault_id,
                    relative_path,
                    int(value.get("chunk_index", 0)),
                    text,
                    value.get("page"),
                    section or None,
                    heading or None,
                    value.get("line_start"),
                    value.get("line_end"),
                    value.get("slide"),
                    value.get("sheet"),
                    value.get("cell_range"),
                    value.get("char_start"),
                    value.get("char_end"),
                    metadata_json,
                ),
            )
            self.db.execute(
                """INSERT INTO chunks_fts
                   (id, file_id, vault_id, relative_path, filename, text, heading, section)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk_id,
                    file_id,
                    vault_id,
                    relative_path,
                    filename,
                    text,
                    heading,
                    section,
                ),
            )

    def remove_file_content(self, file_id: str) -> None:
        self.db.execute("DELETE FROM chunks_fts WHERE file_id = ?", (file_id,))
        self.db.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

    def get_tags(self, file_id: str) -> list[str]:
        rows = self.db.fetch_all(
            "SELECT tag FROM file_tags WHERE file_id = ? ORDER BY tag_key",
            (file_id,),
        )
        return [row["tag"] for row in rows]

    def add_tag(self, file_id: str, tag: str) -> None:
        clean = tag.strip()
        if not clean:
            raise ValueError("Tag cannot be empty.")
        self.db.execute(
            """INSERT INTO file_tags(file_id, tag, tag_key, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(file_id, tag_key) DO UPDATE SET tag=excluded.tag""",
            (file_id, clean, clean.casefold(), datetime.now(timezone.utc).isoformat()),
        )

    def remove_tag(self, file_id: str, tag: str) -> bool:
        cursor = self.db.execute(
            "DELETE FROM file_tags WHERE file_id = ? AND tag_key = ?",
            (file_id, tag.strip().casefold()),
        )
        return cursor.rowcount > 0

    def start_index_run(self, vault_id: str, scope: str | None = None) -> str:
        run_id = str(uuid.uuid4())
        self.db.execute(
            """INSERT INTO index_runs(run_id, vault_id, scope, started_at, status)
               VALUES (?, ?, ?, ?, 'running')""",
            (run_id, vault_id, scope, datetime.now(timezone.utc).isoformat()),
        )
        return run_id

    def finish_index_run(
        self,
        run_id: str,
        *,
        status: str,
        discovered: int = 0,
        created: int = 0,
        updated: int = 0,
        moved: int = 0,
        deleted: int = 0,
        unchanged: int = 0,
        failed: int = 0,
        truncated: int = 0,
        error: str | None = None,
    ) -> None:
        if status not in {"complete", "partial", "failed", "cancelled"}:
            raise ValueError(f"Unsupported index run status: {status}")
        self.db.execute(
            """UPDATE index_runs SET finished_at=?, status=?, discovered=?,
                      created=?, updated=?, moved=?, deleted=?, unchanged=?,
                      failed=?, truncated=?, error=? WHERE run_id=?""",
            (
                datetime.now(timezone.utc).isoformat(),
                status,
                discovered,
                created,
                updated,
                moved,
                deleted,
                unchanged,
                failed,
                truncated,
                error,
                run_id,
            ),
        )
