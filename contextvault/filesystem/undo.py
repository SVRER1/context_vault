import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from contextvault.storage.database import Database
from contextvault.core.vault import Vault
from contextvault.core.models import OperationRecord
from contextvault.filesystem.operations import FileOperations
from contextvault.core.exceptions import UndoError
from contextvault.indexing.fingerprint import compute_sha256

class UndoManager:
    """
    Manages reversing recorded file operations.
    """
    
    def __init__(self, db: Database, vault: Vault):
        self.db = db
        self.vault = vault
        self.file_ops = FileOperations(db)
        
    def _row_to_op(self, row: dict) -> OperationRecord:
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

    def _get_operation(self, operation_id: str) -> Optional[OperationRecord]:
        row = self.db.fetch_one("SELECT * FROM operations WHERE operation_id = ?", (operation_id,))
        if row:
            return self._row_to_op(row)
        return None

    def can_undo(self, operation_id: str) -> bool:
        op = self._get_operation(operation_id)
        if not op or op.status != "completed" or op.undo_status == "undone":
            return False

        if op.operation_type in ("move", "rename"):
            if not op.destination_path:
                return False
            try:
                raw_dest = self.vault.root_path / op.destination_path
                raw_source = self.vault.root_path / op.source_path
                if raw_dest.is_symlink() or raw_source.is_symlink():
                    return False
                curr_dest = self.vault.validate_path(raw_dest)
                orig_src = self.vault.validate_path(raw_source)
                expected_hash = op.hash_after or op.hash_before
                return bool(
                    expected_hash
                    and curr_dest.is_file()
                    and not curr_dest.is_symlink()
                    and compute_sha256(curr_dest) == expected_hash
                    and not orig_src.exists()
                    and not orig_src.is_symlink()
                )
            except (OSError, ValueError, RuntimeError):
                return False

        elif op.operation_type == "create_directory":
            if not op.destination_path:
                return False
            try:
                created_dir = self.vault.validate_path(self.vault.root_path / op.destination_path)
            except (OSError, ValueError, RuntimeError):
                return False
            
            return created_dir.exists() and created_dir.is_dir() and not any(created_dir.iterdir())

        return False
        
    def undo_operation(self, operation_id: str) -> OperationRecord:
        op = self._get_operation(operation_id)
        if not op:
            raise UndoError(f"Operation {operation_id} not found.")
            
        if not self.can_undo(operation_id):
            raise UndoError(f"Cannot undo operation {operation_id}. Current filesystem state prevents safe reversal.")

        if op.operation_type in ("move", "rename"):
            curr_dest = self.vault.root_path / op.destination_path
            orig_src = self.vault.root_path / op.source_path
            
            
            undo_record = self.file_ops.move_file(
                source=curr_dest,
                dest=orig_src,
                vault=self.vault,
                reason=f"Undo operation {operation_id}"
            )
            undo_record.operation_type = f"undo_{op.operation_type}"

        elif op.operation_type == "create_directory":
            created_dir = self.vault.root_path / op.destination_path
            created_dir.rmdir()
            undo_record = OperationRecord(
                operation_id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                vault_id=self.vault.vault_id,
                operation_type="undo_create_directory",
                source_path=op.destination_path,
                destination_path=None,
                hash_before=None,
                hash_after=None,
                status="completed",
                reason=f"Undo created directory {op.destination_path}",
                user_approved=True,
                batch_id=op.batch_id,
                undo_status="undone",
            )
        else:
            raise UndoError(f"Unsupported operation type for undo: {op.operation_type}")

        
        self.db.execute(
            "UPDATE operations SET undo_status = 'undone' WHERE operation_id = ?",
            (operation_id,)
        )
        self.db.conn.commit()
        return undo_record

    def can_undo_journal_item(self, item_id: str) -> bool:
        row = self.db.fetch_one(
            """SELECT i.*,b.vault_id FROM operation_items_v3 i
               JOIN operation_batches_v3 b ON b.batch_id=i.batch_id
               WHERE i.item_id=? AND b.vault_id=?""",
            (item_id, self.vault.vault_id),
        )
        if not row or row["state"] != "committed" or row["action"] != "move" or row["undo_status"] != "none":
            return False
        try:
            destination = self.vault.validate_path(self.vault.root_path / row["destination_path"])
            source = self.vault.validate_path(self.vault.root_path / row["source_path"])
            expected = row["after_hash"] or row["before_hash"]
            return bool(destination.is_file() and not destination.is_symlink()
                        and compute_sha256(destination) == expected
                        and not source.exists() and not source.is_symlink())
        except (OSError, ValueError, RuntimeError):
            return False

    def undo_journal_item(self, item_id: str, *, approved: bool):
        if not approved:
            raise UndoError("Explicit approval is required to undo a journaled operation.")
        if not self.can_undo_journal_item(item_id):
            raise UndoError("The moved bytes or original path changed; safe undo is unavailable.")
        from types import SimpleNamespace
        from contextvault.filesystem.execution_service import ExecutionService, _now
        from contextvault.filesystem.plan_models import FileFingerprint

        original = self.db.fetch_one(
            """SELECT i.*,b.plan_id,b.vault_id FROM operation_items_v3 i
               JOIN operation_batches_v3 b ON b.batch_id=i.batch_id WHERE i.item_id=?""",
            (item_id,),
        )
        plan_row = self.db.fetch_one("SELECT plan_json FROM file_operation_plans WHERE plan_id=?", (original["plan_id"],))
        import json
        plan = json.loads(plan_row["plan_json"])
        reverse_source = original["destination_path"]
        reverse_destination = original["source_path"]
        source_path = self.vault.root_path / reverse_source
        stat = source_path.stat()
        reverse_item = SimpleNamespace(
            file_id=original["file_id"], source=reverse_source,
            destination=reverse_destination, action="move",
            source_fingerprint=FileFingerprint(stat.st_size, stat.st_mtime_ns, original["after_hash"] or original["before_hash"]),
        )
        service = ExecutionService(self.vault, self.db)
        root = self.vault.scope_root(plan.get("scope"))
        self.vault.validate_path(source_path).relative_to(root)
        self.vault.validate_path(self.vault.root_path / reverse_destination).relative_to(root)
        batch_id = str(uuid.uuid4())
        undo_item_id = str(uuid.uuid4())
        now = datetime.now().astimezone().isoformat()
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO operation_batches_v3(batch_id,plan_id,vault_id,status,created_at,updated_at) VALUES(?,?,?,'undo_prepared',?,?)",
                (batch_id, original["plan_id"], self.vault.vault_id, now, now),
            )
            self.db.execute(
                """INSERT INTO operation_items_v3
                   (item_id,batch_id,plan_item_index,file_id,action,source_path,destination_path,
                    before_hash,expected_size,state,undo_of_item_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,'prepared',?,?,?)""",
                (undo_item_id,batch_id,original["plan_item_index"],original["file_id"],"move",
                 reverse_source,reverse_destination,reverse_item.source_fingerprint.sha256,
                 stat.st_size,item_id,now,now),
            )
        try:
            service._execute_item(batch_id, undo_item_id, reverse_item)
            service._set_batch(batch_id, "undone")
            self.db.execute("UPDATE operation_items_v3 SET undo_status='undone',undo_batch_id=? WHERE item_id=?",
                            (batch_id,item_id))
            state = self.db.fetch_one(
                "SELECT count(*) AS total, sum(CASE WHEN undo_status='undone' THEN 1 ELSE 0 END) AS undone FROM operation_items_v3 WHERE batch_id=?",
                (original["batch_id"],),
            )
            if state and state["total"] and state["total"] == state["undone"]:
                service._set_batch(original["batch_id"], "undone")
            self.db.conn.commit()
            return {"batch_id": batch_id, "item_id": item_id, "status": "undone"}
        except Exception as exc:
            service._set_item(undo_item_id, "needs_recovery", error=str(exc))
            service._set_batch(batch_id, "needs_recovery", str(exc))
            raise UndoError(f"Undo batch {batch_id} needs recovery: {exc}") from exc
        
    def undo_batch(self, batch_id: str) -> List[OperationRecord]:
        return self.undo_batch_report(batch_id)["successes"]

    def undo_batch_report(self, batch_id: str) -> dict:
        rows = self.db.fetch_all(
            "SELECT * FROM operations WHERE batch_id = ? AND status = 'completed' AND undo_status = 'none' ORDER BY timestamp DESC",
            (batch_id,)
        )
        undo_records: List[OperationRecord] = []
        refused = []
        for row in rows:
            op_id = row["operation_id"]
            if self.can_undo(op_id):
                try:
                    undo_records.append(self.undo_operation(op_id))
                except Exception as exc:
                    refused.append({"operation_id": op_id, "reason": str(exc)})
            else:
                refused.append({"operation_id": op_id, "reason": "Current paths or hashes do not prove safe reversal."})
        return {"successes": undo_records, "refused": refused,
                "status": "undone" if rows and len(undo_records) == len(rows) else "partial" if undo_records else "refused"}
