from pathlib import Path
from contextvault.core.models import VaultInfo
from contextvault.core.paths import resolve_path
from contextvault.core.exceptions import PathSecurityError
from contextvault.core.config import get_config

class Vault:
    def __init__(self, vault_info: VaultInfo):
        self._vault_info = vault_info
        self._root_path = Path(vault_info.absolute_path).resolve()
        
    @property
    def root_path(self) -> Path:
        return self._root_path
        
    @property
    def vault_id(self) -> str:
        return self._vault_info.id
        
    @property
    def display_name(self) -> str:
        return self._vault_info.display_name
        
    def validate_path(self, path: Path | str) -> Path:
        """Ensures path is within the vault boundary."""
        return resolve_path(path, self._root_path)
        
    def relative_path(self, abs_path: Path | str) -> str:
        """Returns relative path from vault root."""
        resolved = self.validate_path(abs_path)
        return str(resolved.relative_to(self._root_path))
        
    def absolute_path(self, rel_path: str) -> Path:
        """Converts a relative path to an absolute vault path."""
        abs_p = self._root_path / rel_path
        return self.validate_path(abs_p)

    def scope_root(self, subfolder: str | None = None) -> Path:
        """Return the selected source-of-truth directory inside this vault."""
        if not subfolder or not subfolder.strip("/\\"):
            return self._root_path
        scope = self.validate_path(self._root_path / subfolder.strip("/\\"))
        if not scope.is_dir():
            raise ValueError(f"Scope is not a directory inside the vault: {subfolder}")
        return scope

    def is_in_scope(self, path: Path | str, subfolder: str | None = None) -> bool:
        """Check that a vault-relative or absolute path belongs to a selected scope."""
        try:
            resolved = self.validate_path(path if Path(path).is_absolute() else self._root_path / path)
            resolved.relative_to(self.scope_root(subfolder))
            return True
        except (ValueError, OSError, RuntimeError, PathSecurityError):
            return False

    def scope_relative_path(self, subfolder: str | None = None) -> str | None:
        """Return a normalized vault-relative scope string, or None for the whole vault."""
        scope = self.scope_root(subfolder)
        if scope == self._root_path:
            return None
        return str(scope.relative_to(self._root_path)).replace("\\", "/")
        
    @property
    def generated_dir(self) -> Path:
        config = get_config()
        gen_dir = self.validate_path(self._root_path / config.generated_output_folder)
        if gen_dir == self._root_path or gen_dir.exists() and not gen_dir.is_dir():
            raise ValueError("Generated output folder must be a child directory of the vault.")
        return gen_dir
