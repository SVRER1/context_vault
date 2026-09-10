"""Shallow Directory and File Peeker for Context Vault.

Enforces the 10-20 line inspection rule so the local agent
has sufficient semantic context to understand file types and content
without exceeding its context window.
"""

import csv
import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from contextvault.core.vault import Vault

logger = logging.getLogger(__name__)

DEFAULT_MAX_LINES = 15
MIN_LINES = 10
MAX_LINES = 20

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp",
    ".exe", ".dll", ".bin", ".pyc", ".pyd", ".o", ".obj",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".db", ".sqlite", ".sqlite3", ".npy", ".npz",
}


class ShallowPeeker:
    """Safely peeks at file contents, strictly capped at 10-20 lines per file."""

    @staticmethod
    def clamp_lines(lines: int) -> int:
        return max(MIN_LINES, min(MAX_LINES, lines))

    @classmethod
    def peek_file(cls, file_path: Path, max_lines: int = DEFAULT_MAX_LINES) -> Dict[str, Any]:
        """Read strictly up to max_lines (clamped to 10-20) from any supported file."""
        max_lines = cls.clamp_lines(max_lines)

        if not file_path.exists() or not file_path.is_file():
            return {
                "filename": file_path.name,
                "error": "File does not exist",
                "preview": "",
                "line_count": 0,
            }

        ext = file_path.suffix.lower()
        size = file_path.stat().st_size

                                                
        if ext in BINARY_EXTENSIONS:
            return {
                "filename": file_path.name,
                "extension": ext,
                "mime_family": "binary",
                "size_bytes": size,
                "preview": f"[Binary {ext} file, {size:,} bytes]",
                "line_count": 0,
            }

        try:
            if ext in (".csv", ".tsv"):
                return cls._peek_csv(file_path, max_lines, size)
            elif ext == ".xlsx":
                return cls._peek_xlsx(file_path, max_lines, size)
            elif ext == ".pdf":
                return cls._peek_pdf(file_path, max_lines, size)
            elif ext == ".docx":
                return cls._peek_docx(file_path, max_lines, size)
            else:
                return cls._peek_plaintext(file_path, max_lines, size)
        except Exception as e:
            logger.warning(f"Could not peek {file_path.name}: {e}")
            return {
                "filename": file_path.name,
                "extension": ext,
                "size_bytes": size,
                "preview": f"[Could not peek content: {e}]",
                "line_count": 0,
            }

    @staticmethod
    def _peek_plaintext(file_path: Path, max_lines: int, size: int) -> Dict[str, Any]:
        lines: List[str] = []
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                with open(file_path, "r", encoding=encoding, errors="ignore") as f:
                    for _ in range(max_lines * 2):
                        line = f.readline()
                        if not line:
                            break
                        s_line = line.strip()
                        if s_line:
                            lines.append(s_line)
                        if len(lines) >= max_lines:
                            break
                break
            except Exception:
                continue

        preview_text = "\n".join(lines[:max_lines])
        if len(preview_text) > 800:
            preview_text = preview_text[:800] + "..."

                                         
        clean_preview = preview_text.encode("ascii", errors="replace").decode("ascii").replace("?", " ")

        return {
            "filename": file_path.name,
            "extension": file_path.suffix.lower(),
            "mime_family": "text",
            "size_bytes": size,
            "line_count": len(lines[:max_lines]),
            "preview": clean_preview,
        }

    @staticmethod
    def _peek_csv(file_path: Path, max_lines: int, size: int) -> Dict[str, Any]:
        lines: List[str] = []
        columns: List[str] = []
        delimiter = "\t" if file_path.suffix.lower() == ".tsv" else ","

        for encoding in ("utf-8", "latin-1"):
            try:
                with open(file_path, "r", encoding=encoding, errors="ignore") as f:
                    reader = csv.reader(f, delimiter=delimiter)
                    for i, row in enumerate(reader):
                        if not row or not any(row):
                            continue
                        if i == 0:
                            columns = [str(c).strip() for c in row if str(c).strip()]
                        line_repr = " | ".join(str(c) for c in row[:8])
                        lines.append(line_repr)
                        if len(lines) >= max_lines:
                            break
                break
            except Exception:
                continue

        raw_preview = "\n".join(lines[:max_lines])
        clean_preview = raw_preview.encode("ascii", errors="replace").decode("ascii")

        return {
            "filename": file_path.name,
            "extension": file_path.suffix.lower(),
            "mime_family": "data",
            "size_bytes": size,
            "columns": columns,
            "line_count": len(lines),
            "preview": clean_preview,
        }

    @staticmethod
    def _peek_xlsx(file_path: Path, max_lines: int, size: int) -> Dict[str, Any]:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        sheet = wb.active
        lines: List[str] = []
        columns: List[str] = []

        if sheet:
            for i, row in enumerate(sheet.iter_rows(values_only=True)):
                row_vals = [str(v).strip() for v in row if v is not None]
                if not row_vals:
                    continue
                if i == 0:
                    columns = row_vals
                lines.append(" | ".join(row_vals[:8]))
                if len(lines) >= max_lines:
                    break
        wb.close()

        raw_preview = "\n".join(lines[:max_lines])
        clean_preview = raw_preview.encode("ascii", errors="replace").decode("ascii")

        return {
            "filename": file_path.name,
            "extension": ".xlsx",
            "mime_family": "data",
            "size_bytes": size,
            "columns": columns,
            "line_count": len(lines),
            "preview": clean_preview,
        }

    @staticmethod
    def _peek_pdf(file_path: Path, max_lines: int, size: int) -> Dict[str, Any]:
        import pymupdf
        doc = pymupdf.open(str(file_path))
        lines: List[str] = []
        if len(doc) > 0:
            page_text = doc[0].get_text()
            for line in page_text.splitlines():
                s = line.strip()
                if s:
                    lines.append(s)
                if len(lines) >= max_lines:
                    break
        doc.close()

        raw_preview = "\n".join(lines[:max_lines])
        clean_preview = raw_preview.encode("ascii", errors="replace").decode("ascii")

        return {
            "filename": file_path.name,
            "extension": ".pdf",
            "mime_family": "document",
            "size_bytes": size,
            "line_count": len(lines),
            "preview": clean_preview,
        }

    @staticmethod
    def _peek_docx(file_path: Path, max_lines: int, size: int) -> Dict[str, Any]:
        import docx
        doc = docx.Document(str(file_path))
        lines: List[str] = []
        for p in doc.paragraphs:
            s = p.text.strip()
            if s:
                lines.append(s)
            if len(lines) >= max_lines:
                break

        raw_preview = "\n".join(lines[:max_lines])
        clean_preview = raw_preview.encode("ascii", errors="replace").decode("ascii")

        return {
            "filename": file_path.name,
            "extension": ".docx",
            "mime_family": "document",
            "size_bytes": size,
            "line_count": len(lines),
            "preview": clean_preview,
        }

    @classmethod
    def inspect_directory(
        cls,
        vault: Vault,
        subfolder: str = "",
        max_lines_per_file: int = DEFAULT_MAX_LINES,
        max_files: int = 40,
    ) -> List[Dict[str, Any]]:
        """Scan a directory within the vault and peek up to max_lines per file."""
        target_dir = vault.root_path / subfolder if subfolder else vault.root_path
        if not target_dir.exists() or not target_dir.is_dir():
            return []

        profiles: List[Dict[str, Any]] = []
        ignored_names = {".git", ".venv", ".contextvault", "node_modules", "__pycache__", "Generated", ".pytest_cache"}

        for p in sorted(target_dir.rglob("*")):
            if len(profiles) >= max_files:
                break
            if p.is_dir():
                continue
            if any(part in ignored_names for part in p.parts):
                continue

            rel = vault.relative_path(p)
            prof = cls.peek_file(p, max_lines=max_lines_per_file)
            prof["relative_path"] = rel
            profiles.append(prof)

        return profiles

    @classmethod
    def generate_directory_digest(cls, profiles: List[Dict[str, Any]]) -> str:
        """Format a list of file profiles into a compact digest for the LLM."""
        if not profiles:
            return "No files found in directory."

        lines = [f"### Vault Directory Digest ({len(profiles)} files peeked, max 15 lines/file):\n"]
        for p in profiles:
            cols = f" | Columns: {', '.join(p['columns'][:5])}" if p.get("columns") else ""
            lines.append(f"- **`{p.get('relative_path', p.get('filename'))}`** ({p.get('extension', '')}, {p.get('size_bytes', 0):,} B){cols}")
            preview = p.get("preview", "").replace("\n", "  \n> ")
            if preview:
                lines.append(f"> {preview[:220]}")
            lines.append("")

        digest = "\n".join(lines)
        return digest.encode("ascii", errors="replace").decode("ascii")
