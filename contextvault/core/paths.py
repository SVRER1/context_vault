"""Path safety utilities for Context Vault.

This module provides critical security functions to ensure all file operations
remain within the authorized vault boundary. It handles:
- Path resolution and canonicalization
- Symlink and junction traversal
- Case-insensitive Windows paths
- Parent directory (..) escape attempts
"""

import os
from pathlib import Path

from contextvault.core.exceptions import PathSecurityError, VaultBoundaryError


def resolve_path(path: Path | str, vault_root: Path | str) -> Path:
    """Resolve and validate that path is a descendant of vault_root.

    Args:
        path: The path to resolve and validate.
        vault_root: The vault root directory.

    Returns:
        The resolved, validated Path.

    Raises:
        PathSecurityError: If path escapes the vault boundary.
    """
    path_obj = Path(path).resolve()
    vault_root_obj = Path(vault_root).resolve()
    if not is_safe_descendant(path_obj, vault_root_obj):
        raise PathSecurityError(
            f"Path '{path}' resolves outside vault root '{vault_root}'"
        )
    return path_obj


def is_safe_descendant(path: Path | str, vault_root: Path | str) -> bool:
    """Check if path is safely contained within vault_root.

    Uses Path.relative_to() for robust checking instead of string prefix
    matching, which can produce false positives (e.g., /vault-extra matching /vault).

    Handles:
    - Relative paths (resolved to absolute)
    - .. escape attempts
    - Symlinks (resolved via Path.resolve())
    - Case-insensitive Windows paths
    """
    try:
        resolved_path = Path(path).resolve()
        resolved_root = Path(vault_root).resolve()

                                                   
        if os.name == "nt":
            resolved_path = Path(str(resolved_path).lower())
            resolved_root = Path(str(resolved_root).lower())

                                                                     
        resolved_path.relative_to(resolved_root)
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def normalize_vault_path(path: Path | str) -> Path:
    """Resolve path to canonical form.

    On Windows, resolves case and normalizes separators.
    Follows symlinks and junctions.
    """
    return Path(path).resolve()


def validate_vault_boundary(
    source: Path | str, dest: Path | str, vault_root: Path | str
) -> None:
    """Validate that both source and destination are within vault boundary.

    Raises:
        VaultBoundaryError: If either path escapes the vault.
    """
    source_resolved = Path(source).resolve()
    dest_resolved = Path(dest).resolve()
    root_resolved = Path(vault_root).resolve()

    if not is_safe_descendant(source_resolved, root_resolved):
        raise VaultBoundaryError(
            f"Source path '{source}' is outside vault boundary '{vault_root}'"
        )
    if not is_safe_descendant(dest_resolved, root_resolved):
        raise VaultBoundaryError(
            f"Destination path '{dest}' is outside vault boundary '{vault_root}'"
        )


def safe_relative_path(path: Path | str, vault_root: Path | str) -> str:
    """Get the relative path from vault root, with safety check.

    Returns:
        Relative path as string with forward slashes.
    """
    resolved = resolve_path(path, vault_root)
    root = Path(vault_root).resolve()
    return str(resolved.relative_to(root)).replace("\\\\", "/")
