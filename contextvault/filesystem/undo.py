import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from contextvault.storage.database import Database
from contextvault.core.vault import Vault
from contextvault.core.models import OperationRecord
from contextvault.filesystem.operations import FileOperations
from contextvault.core.exceptions import UndoError

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
            curr_dest = self.vault.root_path / op.destination_path
            orig_src = self.vault.root_path / op.source_path
            return curr_dest.exists() and not orig_src.exists()

        elif op.operation_type == "create_directory":
            if not op.destination_path:
                return False
            created_dir = self.vault.root_path / op.destination_path
                                                                     
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
        
    def undo_batch(self, batch_id: str) -> List[OperationRecord]:
        rows = self.db.fetch_all(
            "SELECT * FROM operations WHERE batch_id = ? AND status = 'completed' AND undo_status = 'none' ORDER BY timestamp DESC",
            (batch_id,)
        )
        undo_records: List[OperationRecord] = []
        for row in rows:
            op_id = row["operation_id"]
            if self.can_undo(op_id):
                undo_records.append(self.undo_operation(op_id))
        return undo_records
