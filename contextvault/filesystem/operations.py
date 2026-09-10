import shutil
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from contextvault.core.models import OperationRecord
from contextvault.core.vault import Vault
from contextvault.core.exceptions import FileIntegrityError
from contextvault.indexing.fingerprint import compute_sha256, verify_integrity
from contextvault.filesystem.permissions import PermissionGate
from contextvault.storage.database import Database

logger = logging.getLogger(__name__)

class FileOperations:
    """
    Provides safe file operations with hash verification and boundary enforcement.
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db

    def move_file(
        self,
        source: Path,
        dest: Path,
        vault: Vault,
        reason: str = "Organisation move",
        batch_id: Optional[str] = None,
        user_approved: bool = True,
        operation_type: str = "move",
    ) -> OperationRecord:
        """
        Move a file safely with hash verification before and after.
        """
        source = Path(source).resolve()
        dest = Path(dest).resolve()

        PermissionGate.validate_operation("move", source, dest, vault)
        
                             
        source_hash = compute_sha256(source)
        
                                           
        dest.parent.mkdir(parents=True, exist_ok=True)
        
                         
        shutil.move(str(source), str(dest))
        
                                   
        after_hash = compute_sha256(dest)
        if after_hash != source_hash:
                                            
            try:
                shutil.move(str(dest), str(source))
            except Exception:
                pass
            raise FileIntegrityError(
                f"Hash mismatch after move! Expected {source_hash} but got {after_hash}. File recovered."
            )

        rel_source = vault.relative_path(source) if source.is_relative_to(vault.root_path) else str(source)
        rel_dest = vault.relative_path(dest) if dest.is_relative_to(vault.root_path) else str(dest)

        op_record = OperationRecord(
            operation_id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            vault_id=vault.vault_id,
            operation_type=operation_type,
            source_path=rel_source,
            destination_path=rel_dest,
            hash_before=source_hash,
            hash_after=after_hash,
            status="completed",
            reason=reason,
            user_approved=user_approved,
            batch_id=batch_id,
            undo_status="none"
        )

        if self.db:
            try:
                self.db.execute(
                    """INSERT INTO operations 
                       (operation_id, timestamp, vault_id, operation_type, source_path,
                        destination_path, hash_before, hash_after, status, reason,
                        user_approved, batch_id, undo_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        op_record.operation_id,
                        op_record.timestamp.isoformat(),
                        op_record.vault_id,
                        op_record.operation_type,
                        op_record.source_path,
                        op_record.destination_path,
                        op_record.hash_before,
                        op_record.hash_after,
                        op_record.status,
                        op_record.reason,
                        1 if op_record.user_approved else 0,
                        op_record.batch_id,
                        op_record.undo_status,
                    )
                )
                self.db.conn.commit()
            except Exception as exc:
                logger.exception("Filesystem change completed but audit record failed: %s", exc)

        return op_record

    def rename_file(
        self,
        source: Path,
        new_name: str,
        vault: Vault,
        reason: str = "Rename file",
        batch_id: Optional[str] = None
    ) -> OperationRecord:
        """
        Rename a file safely in the same directory.
        """
        dest = source.with_name(new_name)
        return self.move_file(
            source, dest, vault, reason=reason, batch_id=batch_id,
            operation_type="rename",
        )

    def create_directory(
        self,
        path: Path,
        vault: Vault,
        reason: str = "Create directory",
        batch_id: Optional[str] = None
    ) -> OperationRecord:
        """
        Create a new directory safely within vault.
        """
        path = Path(path).resolve()
        PermissionGate.validate_operation("create_directory", path, path, vault)
        path.mkdir(parents=True, exist_ok=True)
        
        rel_path = vault.relative_path(path) if path.is_relative_to(vault.root_path) else str(path)

        op_record = OperationRecord(
            operation_id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            vault_id=vault.vault_id,
            operation_type="create_directory",
            source_path="",
            destination_path=rel_path,
            hash_before=None,
            hash_after=None,
            status="completed",
            reason=reason,
            user_approved=True,
            batch_id=batch_id,
            undo_status="none"
        )

        if self.db:
            try:
                self.db.execute(
                    """INSERT INTO operations 
                       (operation_id, timestamp, vault_id, operation_type, source_path,
                        destination_path, hash_before, hash_after, status, reason,
                        user_approved, batch_id, undo_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        op_record.operation_id,
                        op_record.timestamp.isoformat(),
                        op_record.vault_id,
                        op_record.operation_type,
                        op_record.source_path,
                        op_record.destination_path,
                        op_record.hash_before,
                        op_record.hash_after,
                        op_record.status,
                        op_record.reason,
                        1 if op_record.user_approved else 0,
                        op_record.batch_id,
                        op_record.undo_status,
                    )
                )
                self.db.conn.commit()
            except Exception as exc:
                logger.exception("Directory change completed but audit record failed: %s", exc)

        return op_record
