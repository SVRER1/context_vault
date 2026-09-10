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
            content = self._read_file(file_path)
        except Exception as e:
            raise ParseError(f"Failed to read file {file_path}: {e}")
            
        if not content.strip():
            return ParsedDocument(
                file_id=file_id,
                title=file_path.name,
                content="",
                sections=[],
                metadata={"source_type": "plaintext"}
            )
            
        title = self._extract_title(content, file_path.name)
        sections = self._split_sections(content)
        
        return ParsedDocument(
            file_id=file_id,
            title=title,
            content=content,
            sections=sections,
            metadata={"source_type": "plaintext"}
        )
        
    def _read_file(self, file_path: Path) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read(self.MAX_SIZE)
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='latin-1') as f:
                return f.read(self.MAX_SIZE)
                
    def _extract_title(self, content: str, filename: str) -> str:
        match = re.search(r'^\s*#\s+(.+)$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return filename
        
    def _split_sections(self, content: str) -> list[DocumentSection]:
        sections = []
        lines = content.split('\n')
        current_title = "Main"
        current_content = []
        
        for line in lines:
            if re.match(r'^\s*#{1,6}\s+', line):
                if current_content:
                    sections.append(DocumentSection(
                        title=current_title,
                        content='\n'.join(current_content).strip(),
                        metadata={"heading": current_title}
                    ))
                current_title = line.strip().lstrip('#').strip()
                current_content = [line]
            else:
                current_content.append(line)
                
        if current_content:
            sections.append(DocumentSection(
                title=current_title,
                content='\n'.join(current_content).strip(),
                metadata={"heading": current_title}
            ))
            
        return sections
