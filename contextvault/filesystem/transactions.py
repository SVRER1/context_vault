import uuid
from pathlib import Path
from contextvault.core.models import OperationRecord, PlannedOperation, OrganisationPlan
from contextvault.core.vault import Vault
from contextvault.storage.database import Database
from contextvault.filesystem.operations import FileOperations
from contextvault.filesystem.permissions import PermissionGate
from contextvault.core.exceptions import PermissionDeniedError

class FileTransaction:
    """
    Manages batched execution of file operations.
    """
    
    def __init__(self, vault: Vault, db: Database):
        self.vault = vault
        self.db = db
        self.operations: list[OperationRecord] = []
        self.batch_id = None
        
    def begin_batch(self, description: str) -> str:
        self.batch_id = str(uuid.uuid4())
        self.operations = []
        return self.batch_id
        
    def add_operation(self, op: OperationRecord):
        self.operations.append(op)
                                      
                                                            
        
    def execute_plan(self, plan: OrganisationPlan, approved: bool) -> list[OperationRecord]:
        if not approved:
            raise PermissionDeniedError("Cannot execute unapproved plan.")
            
        completed_ops = []
        
                                                                              
        for p_op in plan.operations:
            source = self.vault.absolute_path(p_op.source)
            dest = self.vault.absolute_path(p_op.destination or p_op.source)
            PermissionGate.validate_operation(p_op.type, source, dest, self.vault)
            
        self.begin_batch("Execution of organisation plan")
        
        try:
            for rel_dir in plan.directories_to_create:
                self.add_operation(FileOperations.create_directory(
                    self.vault.absolute_path(rel_dir), self.vault,
                    batch_id=self.batch_id,
                ))

            for p_op in plan.operations:
                source = self.vault.absolute_path(p_op.source)
                dest = self.vault.absolute_path(p_op.destination or p_op.source)
                
                if p_op.type == "move":
                    op_record = FileOperations(self.db).move_file(source, dest, self.vault, batch_id=self.batch_id)
                elif p_op.type == "rename":
                    op_record = FileOperations(self.db).rename_file(source, dest.name, self.vault, batch_id=self.batch_id)
                else:
                    continue
                    
                self.add_operation(op_record)
                completed_ops.append(op_record)
                
        except Exception as e:
                                                             
            print(f"Plan execution partially failed: {e}")
            raise e
            
        return completed_ops
