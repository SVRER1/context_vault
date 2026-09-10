from abc import ABC, abstractmethod
from pathlib import Path
from typing import Set
from contextvault.core.models import ParsedDocument

class BaseParser(ABC):
    """Base parser for extracting text content from files."""
    
    @abstractmethod
    def supported_extensions(self) -> set[str]:
        """Return a set of file extensions (e.g., '.txt') supported by this parser."""
        ...
    
    @abstractmethod  
    def parse(self, file_path: Path, file_id: str) -> ParsedDocument:
        """Parse a file and return a ParsedDocument."""
        ...
    
    def can_parse(self, extension: str) -> bool:
        """Check if the given extension is supported by this parser."""
        return extension.lower() in self.supported_extensions()
