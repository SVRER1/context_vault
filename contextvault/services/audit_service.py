"""Audit service for tracking and reverting file operations."""

import logging
from datetime import datetime
from typing import Any

from contextvault.core.models import OperationRecord
from contextvault.core.vault import Vault
from contextvault.filesystem.undo import UndoManager
from contextvault.storage.database import Database

logger = logging.getLogger(__name__)


class AuditService:
    """Service for auditing and undoing file operations."""

    def __init__(self, db: Database):
        self.db = db

    def record_operation(self, op: OperationRecord) -> None:
        """Record a file operation in the audit log."""
        self.db.execute(
            """INSERT INTO operations 
               (operation_id, timestamp, vault_id, operation_type, source_path,
                destination_path, hash_before, hash_after, status, reason,
                user_approved, batch_id, undo_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                op.operation_id,
                op.timestamp.isoformat(),
                op.vault_id,
                op.operation_type,
                op.source_path,
                op.destination_path,
                op.hash_before,
                op.hash_after,
                op.status,
                op.reason,
                1 if op.user_approved else 0,
                op.batch_id,
                op.undo_status,
            ),
        )
        self.db.conn.commit()

    def get_operations(self, vault_id: str, limit: int = 50) -> list[OperationRecord]:
        """Get recent operations for a vault."""
        rows = self.db.fetch_all(
            """SELECT * FROM operations WHERE vault_id = ? 
               ORDER BY timestamp DESC LIMIT ?""",
            (vault_id, limit),
        )
        return [self._row_to_record(row) for row in rows]

    def get_batch(self, batch_id: str) -> list[OperationRecord]:
        """Get all operations in a specific batch."""
        rows = self.db.fetch_all(
            "SELECT * FROM operations WHERE batch_id = ? ORDER BY timestamp",
            (batch_id,),
        )
        return [self._row_to_record(row) for row in rows]

    def undo_operation(self, operation_id: str, vault: Vault) -> OperationRecord:
        """Undo a specific operation."""
        undo_mgr = UndoManager(self.db, vault)
        return undo_mgr.undo_operation(operation_id)

    def undo_batch(self, batch_id: str, vault: Vault) -> list[OperationRecord]:
        """Undo an entire batch of operations (in reverse order)."""
        undo_mgr = UndoManager(self.db, vault)
        return undo_mgr.undo_batch(batch_id)

    def undo_batch_report(self, batch_id: str, vault: Vault) -> dict:
        return UndoManager(self.db, vault).undo_batch_report(batch_id)

    def get_undoable_operations(self, vault_id: str) -> list[OperationRecord]:
        """Get operations that can currently be undone."""
        rows = self.db.fetch_all(
            """SELECT * FROM operations 
               WHERE vault_id = ? AND status = 'completed' AND undo_status = 'none'
               ORDER BY timestamp DESC""",
            (vault_id,),
        )
        return [self._row_to_record(row) for row in rows]

    def get_journal_history(self, vault: Vault, limit: int = 50) -> list[dict]:
        """Return durable plan batches with per-item observed recovery assessments."""
        from contextvault.filesystem.recovery import RecoveryService

        return RecoveryService(vault, self.db).history(limit=limit)

    def inspect_journal_batch(self, batch_id: str, vault: Vault):
        from contextvault.filesystem.recovery import RecoveryService

        return RecoveryService(vault, self.db).inspect_batch(batch_id)

    def recover_journal_batch(self, batch_id: str, vault: Vault, *, approved: bool) -> dict:
        from contextvault.filesystem.recovery import RecoveryService

        return RecoveryService(vault, self.db).recover(batch_id, approved=approved)

    def can_undo_journal_item(self, item_id: str, vault: Vault) -> bool:
        from contextvault.filesystem.undo import UndoManager

        return UndoManager(self.db, vault).can_undo_journal_item(item_id)

    def undo_journal_item(self, item_id: str, vault: Vault, *, approved: bool) -> dict:
        from contextvault.filesystem.undo import UndoManager

        return UndoManager(self.db, vault).undo_journal_item(item_id, approved=approved)

    def undo_journal_batch(self, batch_id: str, vault: Vault, *, approved: bool) -> dict:
        if not approved:
            raise PermissionError("Explicit approval is required to undo a journal batch.")
        rows = self.db.fetch_all(
            "SELECT item_id FROM operation_items_v3 WHERE batch_id=? ORDER BY plan_item_index DESC",
            (batch_id,),
        )
        manager = UndoManager(self.db, vault)
        outcomes = []
        for row in rows:
            item_id = row["item_id"]
            if not manager.can_undo_journal_item(item_id):
                outcomes.append({"item_id": item_id, "status": "refused", "reason": "copy, already undone, or current paths/hashes do not prove safe reversal"})
                continue
            try:
                outcomes.append(manager.undo_journal_item(item_id, approved=True))
            except Exception as exc:
                outcomes.append({"item_id": item_id, "status": "failed", "reason": str(exc)})
        undone = sum(row.get("status") == "undone" for row in outcomes)
        status = "undone" if undone == len(rows) and rows else "partial" if undone else "refused"
        return {"batch_id": batch_id, "status": status, "items": outcomes}

    def _row_to_record(self, row: dict) -> OperationRecord:
        """Convert a database row to an OperationRecord."""
        return OperationRecord(
            operation_id=row["operation_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            vault_id=row["vault_id"],
            operation_type=row["operation_type"],
            source_path=row["source_path"],
            destination_path=row.get("destination_path"),
            hash_before=row.get("hash_before"),
            hash_after=row.get("hash_after"),
            status=row["status"],
            reason=row.get("reason"),
            user_approved=bool(row.get("user_approved", 0)),
            batch_id=row.get("batch_id"),
            undo_status=row.get("undo_status", "none"),
        )
