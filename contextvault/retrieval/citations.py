from typing import List, Any
from contextvault.core.models import Citation, ChunkRecord, SearchResult

class CitationBuilder:
    """Builds and formats citations from search results or chunks."""
    
    @staticmethod
    def build_citations(items: List[Any]) -> List[Citation]:
        """Converts SearchResults, ChunkRecords, or dicts to Citations, deduplicating appropriately."""
        citations: List[Citation] = []
        seen = set()
        
        for item in items:
            file_path = ""
            page = None
            section = None
            heading = None
            preview = ""

            if isinstance(item, ChunkRecord):
                file_path = item.relative_path
                page = item.page
                section = item.section
                heading = item.heading
                preview = item.text[:150].strip() + ("..." if len(item.text) > 150 else "")
            elif isinstance(item, SearchResult):
                file_path = item.relative_path
                page = item.page
                section = item.section
                heading = None
                preview = item.snippet[:150].strip() + ("..." if len(item.snippet) > 150 else "")
            elif isinstance(item, dict):
                file_path = item.get("relative_path") or item.get("file_path", "unknown")
                page = item.get("page")
                section = item.get("section")
                heading = item.get("heading")
                text = item.get("text") or item.get("snippet") or item.get("content", "")
                preview = text[:150].strip() + ("..." if len(text) > 150 else "")
            elif hasattr(item, "relative_path"):
                file_path = getattr(item, "relative_path", "unknown")
                page = getattr(item, "page", None)
                section = getattr(item, "section", None)
                heading = getattr(item, "heading", None)
                text = getattr(item, "text", "") or getattr(item, "snippet", "")
                preview = text[:150].strip() + ("..." if len(text) > 150 else "")

            dedup_key = f"{file_path}_{page}_{section}_{heading}"
            if dedup_key not in seen:
                seen.add(dedup_key)
                citations.append(Citation(
                    file_path=file_path,
                    page=page,
                    section=section,
                    heading=heading,
                    chunk_text_preview=preview,
                ))
                
        return citations
        
    @staticmethod
    def format_citation_cli(citation: Citation, index: int = 1) -> str:
        """Formats citation for command-line output."""
        details = []
        if citation.page is not None:
            details.append(f"p.{citation.page}")
        if citation.section:
            details.append(f"§{citation.section}")
        if citation.heading:
            details.append(f"{citation.heading}")
            
        loc = f" · {', '.join(details)}" if details else ""
        return f"[{index}] {citation.file_path}{loc}"
        
    @staticmethod
    def format_citation_desktop(citation: Citation) -> str:
        """Formats citation for desktop UI (Markdown)."""
        loc = []
        if citation.page is not None:
            loc.append(f"Page {citation.page}")
        if citation.section or citation.heading:
            loc.append(citation.heading or citation.section or "")
            
        loc_str = f" — {', '.join(loc)}" if loc else ""
        return f"**{citation.file_path}**{loc_str}\n> {citation.chunk_text_preview}\n"
