"""Incremental, authoritative reconciliation of a vault's local index."""

from __future__ import annotations

import mimetypes
import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from contextvault.core.models import FileRecord
from contextvault.core.vault import Vault
from contextvault.indexing.chunker import DocumentChunker
from contextvault.indexing.extraction import DocumentExtractor
from contextvault.indexing.fingerprint import compute_sha256
from contextvault.retrieval.filesystem_policy import is_ignored_source_path
from contextvault.storage.database import Database
from contextvault.storage.index_repository import IndexRepository
from contextvault.storage.migrations import normalize_relative_path


class IndexService:
    """Reconcile file metadata and extracted passages without rebuilding clean rows."""

    _locks_guard = RLock()
    _vault_locks: dict[str, RLock] = {}

    def __init__(self, vault: Vault, db: Database, config: Any):
        self.vault = vault
        self.db = db
        self.config = config
        self.repository = IndexRepository(db)
        self.extractor = DocumentExtractor()
        self.chunker = DocumentChunker()
        with self._locks_guard:
            self._lock = self._vault_locks.setdefault(vault.vault_id, RLock())

    def reconcile(
        self,
        scope: str | None = None,
        force: bool = False,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        """Discover and reconcile one complete scope; prune only after safe traversal."""
        with self._lock:
            return self._reconcile(scope, force, progress_callback)

    def _reconcile(self, scope, force, progress_callback):
        scope_path = self.vault.scope_root(scope)
        scope_rel = self.vault.scope_relative_path(scope)
        run_id = self.repository.start_index_run(self.vault.vault_id, scope_rel)
        stats: dict[str, Any] = {
            "discovered": 0, "created": 0, "updated": 0, "moved": 0,
            "deleted": 0, "unchanged": 0, "failed": 0, "truncated": 0,
        }
        try:
            discovered = self._discover(scope_path)
        except Exception as exc:
            self.repository.finish_index_run(run_id, status="failed", error=str(exc))
            self.db.conn.commit()
            stats.update(status="failed", error=str(exc), index_run_id=run_id)
            return stats

        stats["discovered"] = len(discovered)
        old_rows = self.db.fetch_all(
            "SELECT * FROM files WHERE vault_id = ?", (self.vault.vault_id,)
        )
        old_in_scope = {
            row["id"]: row for row in old_rows
            if scope_rel is None or self._in_relative_scope(row["relative_path"], scope_rel)
        }
        old_by_key = {row["path_key"] or row["relative_path"].replace("\\", "/").casefold(): row for row in old_in_scope.values()}
        current_keys = {rel.casefold() for rel, _path, _stat in discovered}
        missing_rows = [row for row in old_in_scope.values() if (row["path_key"] or row["relative_path"].casefold()) not in current_keys]

        
        
        missing_by_fingerprint: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for row in missing_rows:
            if row.get("sha256"):
                missing_by_fingerprint.setdefault((int(row["size"]), row["sha256"]), []).append(row)

        missing_by_path = {
            normalize_relative_path(row["relative_path"]).casefold(): row
            for row in missing_rows
        }
        ledger_moves: dict[str, list[dict[str, Any]]] = {}
        for operation in self.db.fetch_all(
            """SELECT source_path, destination_path, hash_after FROM operations
               WHERE vault_id=? AND status='completed' AND operation_type IN ('move', 'rename')
                 AND destination_path IS NOT NULL""",
            (self.vault.vault_id,),
        ):
            destination = normalize_relative_path(operation["destination_path"]).casefold()
            source_row = missing_by_path.get(normalize_relative_path(operation["source_path"]).casefold())
            if source_row is not None and (not scope_rel or self._in_relative_scope(destination, scope_rel)):
                ledger_moves.setdefault(destination, []).append({"row": source_row, "hash": operation["hash_after"]})

        available_missing = {row["id"]: row for row in missing_rows}
        seen_ids: set[str] = set()
        safe_to_prune = True

        def hash_for_reconcile(path: Path, existing_row):
            nonlocal safe_to_prune
            try:
                return compute_sha256(path)
            except OSError as exc:
                safe_to_prune = False
                stats["failed"] += 1
                if existing_row is not None:
                    file_id = existing_row["id"]
                    seen_ids.add(file_id)
                    available_missing.pop(file_id, None)
                    try:
                        metadata = json.loads(existing_row.get("document_metadata_json") or "{}")
                    except (TypeError, ValueError):
                        metadata = {}
                    with self.db.transaction():
                        self.repository.set_extraction_result(
                            file_id, status="error", parser=existing_row.get("parser"),
                            title=existing_row.get("document_title"), metadata=metadata,
                            error=f"Hash failed: {type(exc).__name__}: {exc}",
                        )
                        self.repository.remove_file_content(file_id)
                return None

        for index, (relative_path, path, stat) in enumerate(discovered, start=1):
            if progress_callback:
                progress_callback(index - 1, len(discovered), f"Checking {path.name}")
            path_key = relative_path.casefold()
            existing = old_by_key.get(path_key)
            content_hash: str | None = None
            if existing is None:
                content_hash = hash_for_reconcile(path, None)
                if content_hash is None:
                    continue
                operation_candidates = [
                    item["row"] for item in ledger_moves.get(path_key, [])
                    if item["row"]["id"] in available_missing
                    and item["row"].get("sha256") == content_hash
                    and (not item["hash"] or item["hash"] == content_hash)
                ]
                candidates = operation_candidates or missing_by_fingerprint.get((stat.st_size, content_hash), [])
                candidates = [row for row in candidates if row["id"] in available_missing]
                if len(candidates) == 1:
                    existing = candidates[0]
                    available_missing.pop(existing["id"], None)
                    stats["moved"] += 1

            if existing is None:
                record_id = str(uuid.uuid4())
                previous_hash = None
                content_changed = True
                stats["created"] += 1
            else:
                record_id = existing["id"]
                seen_ids.add(record_id)
                available_missing.pop(record_id, None)
                same_stat = (
                    int(existing["size"]) == stat.st_size
                    and existing.get("mtime_ns") is not None
                    and int(existing["mtime_ns"]) == stat.st_mtime_ns
                )
                if same_stat and not force:
                    with self.db.transaction():
                        self._refresh_seen_metadata(existing, relative_path, path, stat)
                        self.db.execute(
                            "UPDATE chunks SET relative_path = ? WHERE file_id = ?",
                            (relative_path, record_id),
                        )
                        self.db.execute(
                            "UPDATE chunks_fts SET relative_path = ?, filename = ? WHERE file_id = ?",
                            (relative_path, path.name, record_id),
                        )
                    stats["unchanged"] += 1
                    continue
                if content_hash is None:
                    content_hash = hash_for_reconcile(path, existing)
                    if content_hash is None:
                        continue
                previous_hash = existing.get("sha256")
                content_changed = content_hash != previous_hash or force or (
                    (existing.get("extension") or "").lower() != path.suffix.lower()
                )
                if content_changed:
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1

            if content_hash is None:
                continue
            record = self._record(record_id, relative_path, path, stat, content_hash)
            if not content_changed:
                
                
                with self.db.transaction():
                    self._refresh_seen_metadata(existing, relative_path, path, stat)
                    self.db.execute(
                        "UPDATE chunks SET relative_path = ? WHERE file_id = ?",
                        (relative_path, record_id),
                    )
                    self.db.execute(
                        "UPDATE chunks_fts SET relative_path = ?, filename = ? WHERE file_id = ?",
                        (relative_path, record.filename, record_id),
                    )
                continue

            extraction = self.extractor.extract(path, record_id, record.extension)
            chunks = []
            if extraction.document is not None:
                chunks = self.chunker.chunk(
                    extraction.document,
                    vault_id=self.vault.vault_id,
                    relative_path=relative_path,
                    target_tokens=self.config.chunk_size_tokens,
                    overlap_tokens=self.config.chunk_overlap_tokens,
                )
            else:
                if extraction.status == "error":
                    stats["failed"] += 1
            if extraction.status == "truncated":
                stats["truncated"] += 1

            with self.db.transaction():
                self.repository.upsert_file(record)
                self.repository.set_extraction_result(
                    record_id,
                    status=extraction.status,
                    parser=extraction.parser,
                    word_count=extraction.word_count,
                    title=extraction.document.title if extraction.document else None,
                    metadata=(
                        {**extraction.document.metadata, **extraction.metadata}
                        if extraction.document else extraction.metadata
                    ),
                    error=extraction.error,
                )
                self.repository.replace_file_chunks(
                    record_id, chunks, vault_id=self.vault.vault_id,
                    relative_path=relative_path, filename=record.filename,
                )

        
        if safe_to_prune:
            for file_id, row in available_missing.items():
                with self.db.transaction():
                    self.repository.remove_file_content(file_id)
                    self.db.execute("DELETE FROM files WHERE id = ?", (file_id,))
                stats["deleted"] += 1

        status = "partial" if stats["failed"] else "complete"
        self.repository.finish_index_run(
            run_id,
            status=status,
            discovered=stats["discovered"],
            created=stats["created"],
            updated=stats["updated"],
            moved=stats["moved"],
            deleted=stats["deleted"],
            unchanged=stats["unchanged"],
            failed=stats["failed"],
            truncated=stats["truncated"],
        )
        self.db.conn.commit()
        stats["status"] = status
        stats["index_run_id"] = run_id
        self._refresh_vault_stats()
        if progress_callback:
            progress_callback(len(discovered), len(discovered), "Reconciliation complete")
        return stats

    def _discover(self, root: Path):
        discovered = []
        errors: list[OSError] = []

        def onerror(error):
            errors.append(error)

        for directory, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
            directory_path = Path(directory)
            dirs[:] = sorted(
                name for name in dirs
                if not (directory_path / name).is_symlink()
                and not is_ignored_source_path(directory_path / name, self.config.generated_output_folder)
            )
            for name in sorted(files):
                path = directory_path / name
                if path.is_symlink() or is_ignored_source_path(path, self.config.generated_output_folder):
                    continue
                stat = path.stat(follow_symlinks=False)
                if not path.is_file():
                    continue
                relative = self.vault.relative_path(path).replace("\\", "/")
                discovered.append((relative, path, stat))
        if errors:
            raise errors[0]
        return sorted(discovered, key=lambda item: item[0].casefold())

    def _record(self, file_id: str, relative_path: str, path: Path, stat, digest: str) -> FileRecord:
        extension = path.suffix.lower()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if extension in {".txt", ".md", ".rst", ".log", ".pdf", ".docx", ".pptx", ".csv", ".xlsx"}:
            family = "document"
        elif extension in {".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".rs", ".go", ".cs", ".sql", ".sh", ".ps1"}:
            family = "code"
        elif extension in {".json", ".xml", ".yaml", ".yml", ".toml"}:
            family = "data"
        elif mime_type.startswith("image/"):
            family = "image"
        elif extension in {".zip", ".tar", ".gz", ".rar", ".7z"}:
            family = "archive"
        else:
            family = "other"
        return FileRecord(
            id=file_id, vault_id=self.vault.vault_id, relative_path=relative_path,
            filename=path.name, extension=extension, size=stat.st_size,
            mtime=stat.st_mtime, mtime_ns=stat.st_mtime_ns,
            created_time=stat.st_ctime, ctime_ns=stat.st_ctime_ns,
            sha256=digest, mime_family=family, mime_type=mime_type,
        )

    def _refresh_seen_metadata(self, row, relative_path, path, stat):
        
        
        current = self._record(row["id"], relative_path, path, stat, row["sha256"])
        self.db.execute(
            """UPDATE files SET relative_path=?, path_key=?, parent_path=?, filename=?,
                      extension=?, mime_type=?, size=?, mtime=?, mtime_ns=?,
                      created_time=?, ctime_ns=?, mime_family=? WHERE id=?""",
            (
                current.relative_path, current.relative_path.casefold(), current.relative_path.rpartition("/")[0],
                current.filename, current.extension, current.mime_type, current.size,
                current.mtime, current.mtime_ns, current.created_time, current.ctime_ns,
                current.mime_family, row["id"],
            ),
        )

    @staticmethod
    def _in_relative_scope(relative_path: str, scope: str) -> bool:
        normalized = relative_path.replace("\\", "/").casefold()
        prefix = scope.replace("\\", "/").strip("/").casefold()
        return normalized == prefix or normalized.startswith(prefix + "/")

    def _refresh_vault_stats(self):
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS files FROM files WHERE vault_id = ?", (self.vault.vault_id,)
        )
        chunks = self.db.fetch_one(
            "SELECT COUNT(*) AS chunks FROM chunks WHERE vault_id = ?", (self.vault.vault_id,)
        )
        self.db.execute(
            "UPDATE vaults SET file_count=?, chunk_count=?, last_indexed_at=? WHERE id=?",
            (row["files"], chunks["chunks"], datetime.now(timezone.utc).isoformat(), self.vault.vault_id),
        )
        self.db.conn.commit()
