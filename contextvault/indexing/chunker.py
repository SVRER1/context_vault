import uuid
from typing import List, Optional
from contextvault.core.models import ChunkRecord, ParsedDocument, DocumentSection

class DocumentChunker:
    """Chunks parsed documents into bounded segments for optional local caching."""

    def __init__(self):
        pass

    def _estimate_tokens(self, text: str) -> int:
        """Estimate tokens based on word count (words * 1.3)."""
        if not text:
            return 0
        words = len(text.split())
        return int(words * 1.3)

    def chunk(
        self,
        doc: ParsedDocument,
        vault_id: str = "",
        relative_path: str = "",
        target_tokens: int = 600,
        overlap_tokens: int = 100
    ) -> List[ChunkRecord]:
        """
        Chunks a ParsedDocument into a list of ChunkRecord objects.
        Structure-aware: prefers breaking at headings, paragraphs, pages, slides.
        """
        chunks: List[ChunkRecord] = []
        chunk_index = 0
        rel_path = relative_path or doc.path

                                               
        if not doc.sections:
            if doc.text:
                chunks.extend(self._split_text(
                    text=doc.text,
                    file_id=doc.file_id,
                    vault_id=vault_id,
                    relative_path=rel_path,
                    target_tokens=target_tokens,
                    overlap_tokens=overlap_tokens,
                    start_index=chunk_index
                ))
            return chunks

        for section in doc.sections:
            section_text = section.text or ""
            if not section_text.strip():
                continue

            section_tokens = self._estimate_tokens(section_text)

            if section_tokens <= target_tokens + overlap_tokens:
                                   
                chunk = ChunkRecord(
                    id=str(uuid.uuid4()),
                    file_id=doc.file_id,
                    vault_id=vault_id,
                    relative_path=rel_path,
                    chunk_index=chunk_index,
                    text=section_text.strip(),
                    page=section.page,
                    section=section.sheet or (f"Slide {section.slide}" if section.slide else None),
                    heading=section.heading,
                )
                chunks.append(chunk)
                chunk_index += 1
            else:
                                                  
                section_chunks = self._split_text(
                    text=section_text,
                    file_id=doc.file_id,
                    vault_id=vault_id,
                    relative_path=rel_path,
                    target_tokens=target_tokens,
                    overlap_tokens=overlap_tokens,
                    start_index=chunk_index,
                    page=section.page,
                    heading=section.heading,
                    section=section.sheet or (f"Slide {section.slide}" if section.slide else None)
                )
                chunks.extend(section_chunks)
                chunk_index += len(section_chunks)
                
        return chunks

    def _split_text(
        self,
        text: str,
        file_id: str,
        vault_id: str,
        relative_path: str,
        target_tokens: int,
        overlap_tokens: int,
        start_index: int,
        page: Optional[int] = None,
        heading: Optional[str] = None,
        section: Optional[str] = None
    ) -> List[ChunkRecord]:
        """Splits long text by paragraphs."""
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk_text = ""
        current_chunk_tokens = 0
        chunk_idx = start_index

        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
                
            p_tokens = self._estimate_tokens(p)
            
            if current_chunk_tokens + p_tokens > target_tokens and current_chunk_text:
                chunks.append(ChunkRecord(
                    id=str(uuid.uuid4()),
                    file_id=file_id,
                    vault_id=vault_id,
                    relative_path=relative_path,
                    chunk_index=chunk_idx,
                    text=current_chunk_text.strip(),
                    page=page,
                    heading=heading,
                    section=section
                ))
                chunk_idx += 1
                
                         
                words = current_chunk_text.split()
                overlap_words = int(overlap_tokens / 1.3)
                overlap_text = " ".join(words[-overlap_words:]) if overlap_words > 0 else ""
                current_chunk_text = overlap_text + "\n\n" + p if overlap_text else p
                current_chunk_tokens = self._estimate_tokens(current_chunk_text)
            else:
                current_chunk_text += p + "\n\n"
                current_chunk_tokens += p_tokens

        if current_chunk_text.strip():
            chunks.append(ChunkRecord(
                id=str(uuid.uuid4()),
                file_id=file_id,
                vault_id=vault_id,
                relative_path=relative_path,
                chunk_index=chunk_idx,
                text=current_chunk_text.strip(),
                page=page,
                heading=heading,
                section=section
            ))

        return chunks
