import pytest
from datetime import datetime
from contextvault.core.vault import Vault
from contextvault.core.models import VaultInfo
from contextvault.filesystem.operations import FileOperations
from contextvault.filesystem.permissions import PermissionGate, PermissionDeniedError
from contextvault.core.exceptions import CollisionError, VaultBoundaryError
from contextvault.indexing.fingerprint import compute_sha256
from contextvault.storage.database import Database

@pytest.fixture
def test_vault(tmp_path):
    vault_dir = tmp_path / "test_vault"
    vault_dir.mkdir()
    db_path = tmp_path / "index.db"
    db = Database(db_path)
    db.initialize()
    info = VaultInfo(
        id="test-vault-1",
        display_name="Test Vault",
        absolute_path=str(vault_dir),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
    )
    db.execute(
        """INSERT INTO vaults 
           (id, display_name, absolute_path, created_at, last_opened_at, file_count, chunk_count, index_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (info.id, info.display_name, info.absolute_path, info.created_at.isoformat(), info.last_opened_at.isoformat(), 0, 0, 1)
    )
    db.conn.commit()
    return Vault(info), db

def test_move_verification_hash_preservation(test_vault):
    vault, db = test_vault
    file_ops = FileOperations(db)
    
    src = vault.root_path / "document.txt"
    src.write_text("Unique content that must not change bytes at all.", encoding="utf-8")
    hash_before = compute_sha256(src)
    
    dest = vault.root_path / "Organised" / "document.txt"
    record = file_ops.move_file(src, dest, vault)
    
    assert not src.exists()
    assert dest.exists()
    hash_after = compute_sha256(dest)
    assert hash_before == hash_after
    assert record.hash_before == hash_after
    assert record.status == "completed"
    
                        
    ops = db.fetch_all("SELECT * FROM operations WHERE vault_id = ?", (vault.vault_id,))
    assert len(ops) == 1
    assert ops[0]["operation_type"] == "move"
    assert ops[0]["hash_before"] == hash_before

def test_rename_preserves_bytes(test_vault):
    vault, db = test_vault
    file_ops = FileOperations(db)
    
    src = vault.root_path / "old_name.txt"
    src.write_text("Another immutable file content", encoding="utf-8")
    hash_before = compute_sha256(src)
    
    record = file_ops.rename_file(src, "new_name.txt", vault)
    new_path = vault.root_path / "new_name.txt"
    
    assert not src.exists()
    assert new_path.exists()
    assert compute_sha256(new_path) == hash_before

def test_collision_prevention(test_vault):
    vault, db = test_vault
    file_ops = FileOperations(db)
    
    src = vault.root_path / "a.txt"
    dest = vault.root_path / "b.txt"
    src.write_text("Source bytes", encoding="utf-8")
    dest.write_text("Existing bytes", encoding="utf-8")
    
    with pytest.raises(CollisionError):
        file_ops.move_file(src, dest, vault)
        
    assert src.read_text(encoding="utf-8") == "Source bytes"
    assert dest.read_text(encoding="utf-8") == "Existing bytes"

def test_forbidden_operations_rejected(test_vault):
    vault, _ = test_vault
    file = vault.root_path / "safe.txt"
    file.touch()
    
    with pytest.raises(PermissionDeniedError):
        PermissionGate.validate_operation("delete", file, file, vault)
    with pytest.raises(PermissionDeniedError):
        PermissionGate.validate_operation("overwrite", file, file, vault)
    with pytest.raises(PermissionDeniedError):
        PermissionGate.validate_operation("edit", file, file, vault)
