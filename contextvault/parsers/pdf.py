import fitz           
from pathlib import Path
from contextvault.core.models import ParsedDocument, DocumentSection
from contextvault.core.exceptions import ParseError
from contextvault.parsers.base import BaseParser

class PDFParser(BaseParser):
    """Parser for PDF files using PyMuPDF."""
    
    def supported_extensions(self) -> set[str]:
        return {'.pdf'}
        
    def parse(self, file_path: Path, file_id: str) -> ParsedDocument:
        try:
            doc = fitz.open(str(file_path))
        except Exception as e:
            raise ParseError(f"Failed to open PDF {file_path}: {e}")
            
        if doc.is_encrypted:
            try:
                doc.authenticate("")
            except Exception:
                raise ParseError(f"Cannot parse encrypted PDF {file_path}")
                
        title = doc.metadata.get("title") if doc.metadata else None
        if not title:
            title = file_path.name
            
        sections = []
        full_content = []
        
        try:
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()
                
                if text.strip():
                    full_content.append(text)
                    sections.append(DocumentSection(
                        heading=f"Page {page_num + 1}",
                        text=text.strip(),
                        page=page_num + 1,
                        metadata={"page": page_num + 1}
                    ))
        except Exception as e:
            raise ParseError(f"Error reading PDF pages {file_path}: {e}")
        finally:
            doc.close()
            
        return ParsedDocument(
            file_id=file_id,
            path=str(file_path),
            title=title,
            text='\n\n'.join(full_content),
            sections=sections,
            metadata={"source_type": "pdf", "pages": len(sections)}
        )
