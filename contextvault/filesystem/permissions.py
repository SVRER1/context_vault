from pathlib import Path
from contextvault.core.vault import Vault
from contextvault.core.paths import validate_vault_boundary, resolve_path
from contextvault.core.exceptions import ContextVaultError, CollisionError

class PermissionDeniedError(ContextVaultError):
    pass

class PermissionGate:
    """
    Gatekeeper for all filesystem operations to enforce safety rules.
    """
    
    @staticmethod
    def validate_operation(op_type: str, source: Path, dest: Path, vault: Vault) -> None:
        """
        Check all safety rules for a given operation.
        - Ensure source exists, dest doesn't exist (or handle collision)
        - Ensure both paths within vault boundary
        - Never allow operations on files outside vault
        - No delete permission ever
        - No edit/overwrite permission ever
        """
        if op_type in ("delete", "edit", "overwrite", "truncate"):
            raise PermissionDeniedError(f"Operation type '{op_type}' is strictly forbidden by Context Vault safety rules.")
            
        root = vault.root_path
        
        if op_type == "create_directory":
                                              
            validate_vault_boundary(dest, dest, root)
            return

                             
        if not source.exists():
            raise FileNotFoundError(f"Source file '{source}' does not exist.")
            
        if dest.exists() and source.resolve() != dest.resolve():
            raise CollisionError(f"Destination path '{dest}' already exists. Context Vault will never overwrite existing files.")
            
                                            
        validate_vault_boundary(source, dest, root)
