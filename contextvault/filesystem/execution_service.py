"""Durable, plan-ID-only executor for reviewed file-operation previews."""

from __future__ import annotations

import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from contextvault.core.vault import Vault
from contextvault.filesystem.plan_service import PlanService
from contextvault.filesystem.publication import publish_no_replace
from contextvault.indexing.fingerprint import compute_sha256
from contextvault.storage.database import Database

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True)
class ExecutionResult:
    batch_id: str
    status: str
    completed: tuple[str, ...]
    failed_item: str | None = None
    error: str | None = None


class StaleOperationPlanError(RuntimeError):
    """Raised before mutation when a reviewed plan no longer matches disk."""


class OperationExecutionError(RuntimeError):
    """Raised when a filesystem action has a journaled partial outcome."""


class ExecutionService:
    """Revalidate, journal, execute, and index a persisted immutable plan."""

    def __init__(self, vault: Vault, db: Database, plan_service: PlanService | None = None):
        self.vault = vault
        self.db = db
        self.plans = plan_service or PlanService(vault, db)

    def commit(self, plan_id: str, digest: str, *, approved: bool) -> ExecutionResult:
        if not approved:
            raise PermissionError("Explicit approval is required to commit an operation plan.")
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(self.vault.vault_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise RuntimeError("Another filesystem operation is already running for this vault.")
        try:
            plan = self.plans.get_plan(plan_id)
            if plan.digest != digest:
                raise StaleOperationPlanError("Plan digest does not match the reviewed preview.")
            if plan.status != "preview":
                raise StaleOperationPlanError(f"Plan is {plan.status} and cannot be committed.")
            if plan.conflicts:
                raise StaleOperationPlanError("Plan contains conflicts; resolve them and create a new preview.")
            if plan.vault_id != self.vault.vault_id:
                raise StaleOperationPlanError("Plan belongs to a different vault.")
            self._preflight(plan)

            batch_id = str(uuid.uuid4())
            now = _now()
                                                                                     
            with self.db.transaction():
                self.db.execute(
                    "INSERT INTO operation_batches_v3(batch_id,plan_id,vault_id,status,created_at,updated_at) VALUES(?,?,?,'prepared',?,?)",
                    (batch_id, plan_id, self.vault.vault_id, now, now),
                )
                for index, item in enumerate(plan.items):
                    self.db.execute(
                        """INSERT INTO operation_items_v3
                           (item_id,batch_id,plan_item_index,file_id,action,source_path,destination_path,
                            before_hash,expected_size,state,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?, ?,?,'prepared',?,?)""",
                        (str(uuid.uuid4()), batch_id, index, item.file_id, item.action, item.source,
                         item.destination, item.source_fingerprint.sha256,
                         item.source_fingerprint.size, now, now),
                    )
                self.db.execute(
                    "UPDATE file_operation_plans SET status='committing' WHERE plan_id=? AND status='preview'",
                    (plan_id,),
                )

            completed: list[str] = []
            self._set_batch(batch_id, "started")
            for index, item in enumerate(plan.items):
                row = self.db.fetch_one(
                    "SELECT item_id FROM operation_items_v3 WHERE batch_id=? AND plan_item_index=?",
                    (batch_id, index),
                )
                item_id = row["item_id"]
                try:
                    self._execute_item(batch_id, item_id, item)
                    completed.append(item_id)
                except Exception as exc:
                    self._set_item(item_id, "needs_recovery", error=str(exc))
                    self._set_batch(batch_id, "needs_recovery", str(exc))
                    self.plans.update_status(plan_id, "needs_recovery")
                    return ExecutionResult(batch_id, "needs_recovery", tuple(completed), item_id, str(exc))

            self._set_batch(batch_id, "committed")
            self.plans.update_status(plan_id, "committed")
            return ExecutionResult(batch_id, "committed", tuple(completed))
        finally:
            lock.release()

    def _preflight(self, plan) -> None:
        if not plan.items:
            raise StaleOperationPlanError("Plan contains no file operations.")
        targets: set[str] = set()
        root = self.vault.scope_root(plan.scope)
        for item in plan.items:
            source = self.vault.root_path / item.source
            dest = self.vault.root_path / item.destination
            try:
                source_resolved = self.vault.validate_path(source)
                dest_resolved = self.vault.validate_path(dest)
                source_resolved.relative_to(root)
                dest_resolved.relative_to(root)
            except (OSError, ValueError, RuntimeError) as exc:
                raise StaleOperationPlanError(f"Operation escaped its reviewed scope: {item.source}: {exc}") from exc
            if source.is_symlink() or not source.is_file():
                raise StaleOperationPlanError(f"Source is missing, not a regular file, or is a symlink: {item.source}")
            stat = source.stat()
            if (stat.st_size != item.source_fingerprint.size or
                    stat.st_mtime_ns != item.source_fingerprint.mtime_ns or
                    compute_sha256(source) != item.source_fingerprint.sha256):
                raise StaleOperationPlanError(f"Source changed since preview: {item.source}")
            key = item.destination.casefold()
            if key in targets:
                raise StaleOperationPlanError(f"Duplicate destination in reviewed plan: {item.destination}")
            targets.add(key)
            case_only_rename = item.action == "rename" and item.source.casefold() == item.destination.casefold()
            if case_only_rename and dest.exists():
                try:
                    case_only_rename = os.path.samefile(source, dest)
                except OSError:
                    case_only_rename = False
            if (dest.exists() or dest.is_symlink()) and not case_only_rename:
                raise StaleOperationPlanError(f"Destination appeared since preview: {item.destination}")
            if shutil.disk_usage(dest.parent if dest.parent.exists() else root).free < item.source_fingerprint.size:
                raise OSError(f"Insufficient free space for {item.destination}")

    def _execute_item(self, batch_id: str, item_id: str, item) -> None:
        source = self.vault.root_path / item.source
        destination = self.vault.root_path / item.destination
        self._set_item(item_id, "started", attempt=True)
        self._ensure_safe_parents(destination.parent)
        if item.action == "rename" and item.source.casefold() == item.destination.casefold():
            self._execute_case_only_rename(batch_id, item_id, item, source, destination)
            return
                                                                                
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Destination appeared during commit: {item.destination}")
        if compute_sha256(source) != item.source_fingerprint.sha256:
            raise StaleOperationPlanError(f"Source changed during commit: {item.source}")

        temp = destination.with_name(f".{destination.name}.cv-{uuid.uuid4().hex}.tmp")
        self._set_item(item_id, "copying", temp_path=self.vault.relative_path(temp))
        try:
            with source.open("rb") as src, temp.open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            if compute_sha256(temp) != item.source_fingerprint.sha256:
                raise IOError("Temporary copy checksum did not match the reviewed source.")
            self._set_item(item_id, "destination_verified", after_hash=item.source_fingerprint.sha256)
            publish_no_replace(temp, destination)
            if item.action != "copy":
                if compute_sha256(source) != item.source_fingerprint.sha256:
                    raise StaleOperationPlanError("Source changed after destination publication; source was retained.")
                source.unlink()
                self._set_item(item_id, "source_removed")
            result_file_id = self._update_index(item, destination)
            self._set_item(item_id, "committed", index_applied=True,
                           result_file_id=result_file_id)
        finally:
                                                                                             
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass

    def _execute_case_only_rename(self, batch_id: str, item_id: str, item, source: Path, destination: Path) -> None:
        if compute_sha256(source) != item.source_fingerprint.sha256:
            raise StaleOperationPlanError(f"Source changed during commit: {item.source}")
        intermediate = source.with_name(f".{source.name}.cv-{uuid.uuid4().hex}.rename")
        if intermediate.exists():
            raise FileExistsError(f"Reserved case-rename path already exists: {intermediate.name}")
        self._set_item(item_id, "case_rename_staging", temp_path=self.vault.relative_path(intermediate))
        os.rename(source, intermediate)
        self._set_item(item_id, "source_staged")
        try:
            publish_no_replace(intermediate, destination)
        except Exception:
            if intermediate.exists() and not source.exists() and not destination.exists():
                os.rename(intermediate, source)
            raise
        if compute_sha256(destination) != item.source_fingerprint.sha256:
            raise IOError("Case-only rename checksum did not match the reviewed source.")
        self._set_item(item_id, "destination_verified", after_hash=item.source_fingerprint.sha256)
        result_file_id = self._update_index(item, destination)
        self._set_item(item_id, "committed", index_applied=True, result_file_id=result_file_id)

    def _update_index(self, item, destination: Path) -> str:
        relative = item.destination.replace("\\", "/")
        filename = destination.name
        parent = relative.rpartition("/")[0]
        stat = destination.stat()
        with self.db.transaction():
            if item.action == "copy":
                                                                                              
                self.db.execute("UPDATE files SET last_seen_scan=NULL WHERE id=?", (item.file_id,))
            else:
                self.db.execute(
                    "UPDATE files SET relative_path=?,path_key=?,parent_path=?,filename=?,size=?,mtime=?,mtime_ns=? WHERE id=?",
                    (relative, relative.casefold(), parent, filename, stat.st_size, stat.st_mtime,
                     stat.st_mtime_ns, item.file_id),
                )
                self.db.execute("UPDATE chunks SET relative_path=? WHERE file_id=?", (relative, item.file_id))
                self.db.execute("UPDATE chunks_fts SET relative_path=?,filename=? WHERE file_id=?",
                                 (relative, filename, item.file_id))
        if item.action == "copy":
            from contextvault.indexing.index_service import IndexService
            IndexService(self.vault, self.db, self.plans.config).reconcile()
            copied = self.db.fetch_one(
                "SELECT id FROM files WHERE vault_id=? AND path_key=?",
                (self.vault.vault_id, relative.casefold()),
            )
            if not copied:
                raise RuntimeError("Copied file is present but its new index row was not created.")
            return copied["id"]
        return item.file_id

    def _ensure_safe_parents(self, directory: Path) -> None:
        missing = []
        current = directory
        while current != self.vault.root_path and not current.exists():
            missing.append(current)
            current = current.parent
        self.vault.validate_path(current).relative_to(self.vault.root_path)
        if current.is_symlink():
            raise OSError(f"Destination parent is a symlink: {current}")
        for path in reversed(missing):
            path.mkdir()
            self._journal_directory(path)

    def _journal_directory(self, path: Path) -> None:
                                                                                        
        now = _now()
        self.db.execute(
            "INSERT INTO operations(operation_id,timestamp,vault_id,operation_type,source_path,destination_path,hash_before,hash_after,status,reason,user_approved,batch_id,undo_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), now, self.vault.vault_id, "create_directory", "",
             str(path.relative_to(self.vault.root_path)).replace("\\", "/"), None, None,
             "completed", "Created for reviewed operation", 1, None, "none"),
        )
        self.db.conn.commit()

    def _set_item(self, item_id: str, state: str, *, error: str | None = None,
                  after_hash: str | None = None, temp_path: str | None = None,
                  index_applied: bool | None = None, result_file_id: str | None = None,
                  attempt: bool = False) -> None:
        fields = ["state=?", "updated_at=?"]
        values: list[object] = [state, _now()]
        if error is not None:
            fields.append("error=?"); values.append(error)
        if after_hash is not None:
            fields.append("after_hash=?"); values.append(after_hash)
        if temp_path is not None:
            fields.append("temp_path=?"); values.append(temp_path)
        if index_applied is not None:
            fields.append("index_applied=?"); values.append(int(index_applied))
        if result_file_id is not None:
            fields.append("result_file_id=?"); values.append(result_file_id)
        if attempt:
            fields.append("attempt_count=attempt_count+1")
        values.append(item_id)
        self.db.execute(f"UPDATE operation_items_v3 SET {','.join(fields)} WHERE item_id=?", tuple(values))
        self.db.conn.commit()

    def _set_batch(self, batch_id: str, status: str, error: str | None = None) -> None:
        self.db.execute("UPDATE operation_batches_v3 SET status=?,error=?,updated_at=? WHERE batch_id=?",
                        (status, error, _now(), batch_id))
        self.db.conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
