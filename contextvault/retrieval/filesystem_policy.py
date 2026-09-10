"""Shared source-discovery policy for filesystem-native retrieval."""

from pathlib import Path

from contextvault.core.vault import Vault


IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    ".contextvault",
    ".pytest_cache",
    ".agents",
    ".codex",
    "__pycache__",
    "node_modules",
    "Generated",
}


def is_ignored_source_path(path: Path, generated_output_folder: str = "Generated") -> bool:
    """Return whether a path belongs to an implementation/output subtree."""
    ignored = IGNORED_DIRECTORY_NAMES | {generated_output_folder}
    return any(part in ignored or (part.startswith(".") and part not in {".", ".."}) for part in path.parts)


def validate_source_scope(vault: Vault, source_scope: str | None, generated_output_folder: str = "Generated") -> Path:
    """Validate and return the canonical selected source directory."""
    root = vault.scope_root(source_scope)
    if is_ignored_source_path(root.relative_to(vault.root_path), generated_output_folder):
        raise ValueError("The selected source scope is an internal or generated directory.")
    return root
