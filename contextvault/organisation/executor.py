import logging
from pathlib import Path
from typing import List, Optional
import uuid

from contextvault.core.models import OrganisationPlan, OperationRecord
from contextvault.core.vault import Vault
from contextvault.core.exceptions import OrganisationError
from contextvault.storage.database import Database
from contextvault.filesystem.operations import FileOperations

logger = logging.getLogger(__name__)

class OrganisationExecutor:
    """Executes validated organisation plans safely with hash verification."""
    
    def __init__(self, vault: Vault, db: Database, file_ops: Optional[FileOperations] = None):
        self.vault = vault
        self.db = db
        self.file_ops = file_ops or FileOperations(db)

    def execute(self, plan: OrganisationPlan, approved: bool = True) -> List[OperationRecord]:
        if not approved:
            raise OrganisationError("Cannot execute organisation plan: user approval required.")
            
        completed_operations: List[OperationRecord] = []
        batch_id = str(uuid.uuid4())
        
                                            
        for rel_dir in plan.directories_to_create:
            dir_path = self.vault.root_path / rel_dir
            try:
                op = self.file_ops.create_directory(
                    path=dir_path,
                    vault=self.vault,
                    reason="Create organisation directory",
                    batch_id=batch_id
                )
                completed_operations.append(op)
            except Exception as e:
                logger.warning(f"Directory creation note for '{rel_dir}': {e}")
                
                                            
        for planned_op in plan.operations:
            src_path = self.vault.root_path / planned_op.source
            if not planned_op.destination:
                continue
            dst_path = self.vault.root_path / planned_op.destination
            
            if not src_path.exists():
                logger.warning(f"Source file disappeared: {src_path}")
                continue
                
            try:
                op_record = self.file_ops.move_file(
                    source=src_path,
                    dest=dst_path,
                    vault=self.vault,
                    reason=planned_op.reason,
                    batch_id=batch_id,
                    user_approved=approved
                )
                completed_operations.append(op_record)
            except Exception as e:
                logger.error(f"Failed to move '{src_path}' to '{dst_path}': {e}")
                                                                                     
                break
                
        return completed_operations
