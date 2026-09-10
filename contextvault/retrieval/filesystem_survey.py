"""Cheap, deterministic survey of the selected filesystem source scope."""

import os
from pathlib import Path

from contextvault.core.config import AppConfig, get_config
from contextvault.core.vault import Vault
from contextvault.parsers.registry import create_default_registry
from contextvault.retrieval.filesystem_models import FileSurvey
from contextvault.retrieval.filesystem_policy import (
    IGNORED_DIRECTORY_NAMES,
    is_ignored_source_path,
    validate_source_scope,
)
from contextvault.tools.peeker import ShallowPeeker


class FilesystemSurvey:
    """Survey file topology without opening complete documents."""

    def __init__(self, vault: Vault, config: AppConfig | None = None):
        self.vault = vault
        self.config = config or get_config()
        self.registry = create_default_registry()

    def survey(self, source_scope: str | None = None, max_files: int | None = None) -> list[FileSurvey]:
        scope_root = validate_source_scope(self.vault, source_scope, self.config.generated_output_folder)
        ignored_names = IGNORED_DIRECTORY_NAMES | {self.config.generated_output_folder}
        surveys: list[FileSurvey] = []

        for root, dirs, files in os.walk(scope_root):
            root_path = Path(root)
            dirs[:] = [
                name for name in dirs
                if name not in ignored_names
                and not is_ignored_source_path(root_path / name, self.config.generated_output_folder)
            ]
            for filename in sorted(files, key=str.lower):
                path = root_path / filename
                if is_ignored_source_path(path, self.config.generated_output_folder):
                    continue
                try:
                    stat = path.stat()
                    relative_path = self.vault.relative_path(path).replace("\\", "/")
                    parser = self.registry.get_parser(path.suffix)
                    preview = ShallowPeeker.peek_file(path, max_lines=15).get("preview", "")
                    surveys.append(FileSurvey(
                        relative_path=relative_path,
                        filename=path.name,
                        directory=str(Path(relative_path).parent).replace("\\", "/") if Path(relative_path).parent != Path(".") else "",
                        extension=path.suffix.lower(),
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                        parser=type(parser).__name__ if parser else None,
                        mime_family=self._mime_family(path.suffix),
                        preview=preview,
                    ))
                    if max_files and len(surveys) >= max_files:
                        return surveys
                except (OSError, ValueError):
                    continue
        return surveys

    @staticmethod
    def _mime_family(extension: str) -> str:
        ext = extension.lower()
        if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg"}:
            return "image"
        if ext in {".csv", ".xlsx"}:
            return "data"
        if ext in {".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".rs", ".go", ".cs", ".sql", ".sh", ".ps1"}:
            return "code"
        if ext in {".json", ".xml", ".yaml", ".yml", ".toml"}:
            return "data"
        if ext in {".txt", ".md", ".rst", ".log", ".pdf", ".docx", ".pptx"}:
            return "document"
        return "other"
