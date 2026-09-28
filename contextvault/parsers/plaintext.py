import re
from pathlib import Path
from contextvault.core.models import ParsedDocument, DocumentSection
from contextvault.core.exceptions import ParseError
from contextvault.parsers.base import BaseParser

class PlainTextParser(BaseParser):
    """Parser for plaintext, source code, and markdown files."""
    
    MAX_SIZE = 1024 * 1024  
    
    def supported_extensions(self) -> set[str]:
        return {
            '.txt', '.md', '.rst', '.log', '.py', '.java', '.c', '.cpp', 
            '.h', '.hpp', '.cs', '.rs', '.js', '.ts', '.html', '.css', 
            '.json', '.yaml', '.yml', '.toml', '.xml', '.sql', '.sh', '.ps1'
        }
    
    def parse(self, file_path: Path, file_id: str) -> ParsedDocument:
        if not file_path.exists():
            raise ParseError(f"File not found: {file_path}")
            
        try:
            content, truncated, bytes_read = self._read_file_with_status(file_path)
        except Exception as e:
            raise ParseError(f"Failed to read file {file_path}: {e}")
            
        if not content.strip():
            return ParsedDocument(
                file_id=file_id,
                path=str(file_path),
                title=file_path.name,
                content="",
                sections=[],
                metadata={
                    "source_type": "plaintext",
                    "truncated": truncated,
                    "bytes_read": bytes_read,
                }
            )
            
        title = self._extract_title(content, file_path.name)
        sections = self._split_sections(content)
        
        return ParsedDocument(
            file_id=file_id,
            path=str(file_path),
            title=title,
            content=content,
            sections=sections,
            metadata={
                "source_type": "plaintext",
                "truncated": truncated,
                "bytes_read": bytes_read,
            }
        )
        
    def _read_file(self, file_path: Path) -> str:
        return self._read_file_with_status(file_path)[0]

    def _read_file_with_status(self, file_path: Path) -> tuple[str, bool, int]:
        with open(file_path, "rb") as handle:
            raw = handle.read(self.MAX_SIZE + 1)
        truncated = len(raw) > self.MAX_SIZE
        raw = raw[:self.MAX_SIZE]
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = raw.decode("latin-1")
        return content, truncated, len(raw)
                
    def _extract_title(self, content: str, filename: str) -> str:
        match = re.search(r'^\s*#\s+(.+)$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return filename
        
    def _split_sections(self, content: str) -> list[DocumentSection]:
        sections = []
        lines = content.splitlines(keepends=True)
        current_title = "Main"
        current_content = []
        current_start_line = 1
        current_start_char = 0
        char_offset = 0

        def append_section(end_line: int, end_char: int, level: int | None = None):
            if current_content:
                sections.append(DocumentSection(
                    heading=current_title,
                    text="\n".join(current_content).strip(),
                    line_start=current_start_line,
                    line_end=max(current_start_line, end_line),
                    char_start=current_start_char,
                    char_end=end_char,
                    level=level,
                    metadata={"heading": current_title, "heading_level": level} if level else {"heading": current_title},
                ))

        current_level = None
        for line_number, raw_line in enumerate(lines, start=1):
            line = raw_line.rstrip("\r\n")
            match = re.match(r'^\s*(#{1,6})\s+', line)
            if match:
                append_section(line_number - 1, char_offset, current_level)
                if current_content:
                    current_content = []
                current_title = line.strip().lstrip('#').strip()
                current_level = len(match.group(1))
                current_start_line = line_number
                current_start_char = char_offset
                current_content = [line]
            else:
                current_content.append(line)
            char_offset += len(raw_line)

        append_section(len(lines), len(content), current_level)
        return sections
