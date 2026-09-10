from pathlib import Path
from typing import Optional
from contextvault.core.models import OperationRecord
from contextvault.core.vault import Vault
from contextvault.indexing.fingerprint import compute_sha256

class Verification:
    """
    Provides methods to verify operation integrity.
    """
    
    @staticmethod
    def verify_move(source: Path, dest: Path, expected_hash: str) -> bool:
        if source.exists():
            return False
        if not dest.exists():
            return False
        return compute_sha256(dest) == expected_hash
        
    @staticmethod
    def verify_rename(old_path: Path, new_path: Path, expected_hash: str) -> bool:
        return Verification.verify_move(old_path, new_path, expected_hash)
        
    @staticmethod
    def verify_batch(operations: list[OperationRecord], vault: Optional[Vault] = None) -> list[tuple[OperationRecord, bool]]:
        results = []
        for op in operations:
            if op.operation_type in ("move", "rename"):
                source = Path(op.source_path)
                dest = Path(op.destination_path or "")
                if vault:
                    source = vault.absolute_path(op.source_path)
                    dest = vault.absolute_path(op.destination_path or "")
                valid = Verification.verify_move(source, dest, op.hash_after or op.hash_before or "")
                results.append((op, valid))
            elif op.operation_type == "create_directory":
                dest = vault.absolute_path(op.destination_path or "") if vault else Path(op.destination_path or "")
                valid = dest.exists() and dest.is_dir()
                results.append((op, valid))
            else:
                results.append((op, False))
        return results
