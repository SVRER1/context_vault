"""Application configuration for Context Vault."""

import json
import os
import platform
from pathlib import Path

from pydantic import BaseModel, Field


def _default_app_data_dir() -> str:
    """Get platform-specific application data directory."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return str(Path(base) / "ContextVault")
    else:
        return str(Path.home() / ".local" / "share" / "context-vault")


class AppConfig(BaseModel):
    """Application configuration with sensible defaults."""

    app_data_dir: str = Field(default_factory=_default_app_data_dir)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e2b"
    retrieval_max_rounds: int = 2
    retrieval_max_candidates: int = 20
    retrieval_max_deep_reads: int = 5
    retrieval_context_budget: int = 12000
    retrieval_preview_bytes: int = 16384
    retrieval_max_bytes_per_read: int = 512000
    chunk_size_tokens: int = 600
    chunk_overlap_tokens: int = 100
    generated_output_folder: str = "Generated"
    temperature: float = 0.2
    context_size: int = 2048
    ollama_timeout: int = 60

    @property
    def app_data_path(self) -> Path:
        """Return app_data_dir as a Path object."""
        return Path(self.app_data_dir)

    @property
    def app_db_path(self) -> Path:
        """Path to the main application database."""
        return self.app_data_path / "app.db"

    @property
    def vaults_data_dir(self) -> Path:
        """Directory where vault-specific data is stored."""
        return self.app_data_path / "vaults"

    @property
    def logs_dir(self) -> Path:
        """Directory for application logs."""
        return self.app_data_path / "logs"

    def vault_data_dir(self, vault_id: str) -> Path:
        """Get data directory for a specific vault."""
        return self.vaults_data_dir / vault_id

    def save(self) -> None:
        """Save configuration to config.json."""
        config_path = self.app_data_path / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(self.model_dump(exclude={"app_data_dir"}), f, indent=2)


_config_instance: AppConfig | None = None


def get_config() -> AppConfig:
    """Get the singleton application configuration."""
    global _config_instance
    if _config_instance is None:
        config = AppConfig()
        config_file = config.app_data_path / "config.json"
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    data = json.load(f)
                                                                         
                                                                        
                if data.get("ollama_model") in {
                    "LiquidAI/lfm2.5-1.2b-instruct:latest",
                    "lfm2.5",
                }:
                    data["ollama_model"] = "gemma4:e2b"
                _config_instance = AppConfig(**data)
            except (json.JSONDecodeError, Exception):
                _config_instance = config
        else:
            _config_instance = config
    return _config_instance


def reset_config() -> None:
    """Reset the config singleton (useful for testing)."""
    global _config_instance
    _config_instance = None
