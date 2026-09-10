from typing import Dict, Set, Optional
from contextvault.parsers.base import BaseParser

class ParserRegistry:
    """Registry for managing file parsers."""
    
    def __init__(self):
        self._parsers: Dict[str, BaseParser] = {}
        
    def register(self, parser: BaseParser) -> None:
        """Register a parser for all its supported extensions."""
        for ext in parser.supported_extensions():
            self._parsers[ext.lower()] = parser
            
    def get_parser(self, extension: str) -> Optional[BaseParser]:
        """Get the appropriate parser for a given file extension."""
        return self._parsers.get(extension.lower())
        
    def get_all_supported_extensions(self) -> Set[str]:
        """Get a set of all registered file extensions."""
        return set(self._parsers.keys())

def create_default_registry(ocr_client=None) -> ParserRegistry:
    """Create a ParserRegistry populated with all default parsers."""
    registry = ParserRegistry()
    
    from contextvault.parsers.plaintext import PlainTextParser
    from contextvault.parsers.pdf import PDFParser
    from contextvault.parsers.docx import DOCXParser
    from contextvault.parsers.pptx import PPTXParser
    from contextvault.parsers.spreadsheet import SpreadsheetParser
    from contextvault.parsers.image import ImageOCRParser
    
    registry.register(PlainTextParser())
    registry.register(PDFParser())
    registry.register(DOCXParser())
    registry.register(PPTXParser())
    registry.register(SpreadsheetParser())
    registry.register(ImageOCRParser(ocr_client=ocr_client))
    
    return registry
