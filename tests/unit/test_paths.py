import os
import pytest
from pathlib import Path
from contextvault.core.paths import resolve_path, is_safe_descendant, validate_vault_boundary
from contextvault.core.exceptions import PathSecurityError, VaultBoundaryError

def test_valid_descendant(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    child = vault / "notes" / "todo.txt"
    child.parent.mkdir()
    child.touch()
    
    assert is_safe_descendant(child, vault) is True
    resolved = resolve_path(child, vault)
    assert resolved == child.resolve()

def test_parent_escape_rejected(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    
                          
    outside = vault / ".." / "secret.txt"
    assert is_safe_descendant(outside, vault) is False
    with pytest.raises(PathSecurityError):
        resolve_path(outside, vault)

def test_absolute_external_path_rejected(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    
    external = tmp_path / "outside.txt"
    external.touch()
    
    assert is_safe_descendant(external, vault) is False
    with pytest.raises(PathSecurityError):
        resolve_path(external, vault)

def test_prefix_trick_rejected(tmp_path):
                                 
    vault = tmp_path / "vault"
    vault.mkdir()
    similar = tmp_path / "vault-extra"
    similar.mkdir()
    
    assert is_safe_descendant(similar, vault) is False
    with pytest.raises(PathSecurityError):
        resolve_path(similar, vault)

def test_validate_vault_boundary(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    file_a = vault / "a.txt"
    file_b = vault / "sub" / "b.txt"
    file_a.touch()
    file_b.parent.mkdir()
    
    validate_vault_boundary(file_a, file_b, vault)
    
    external = tmp_path / "external.txt"
    with pytest.raises(VaultBoundaryError):
        validate_vault_boundary(file_a, external, vault)
    with pytest.raises(VaultBoundaryError):
        validate_vault_boundary(external, file_b, vault)
