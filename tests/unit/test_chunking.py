from contextvault.core.models import ParsedDocument, DocumentSection
from contextvault.indexing.chunker import DocumentChunker

def test_document_chunker_basic():
    chunker = DocumentChunker()
    doc = ParsedDocument(
        file_id="f1",
        path="notes.md",
        title="Notes",
        text="Simple content without sections",
        sections=[]
    )
    chunks = chunker.chunk(doc, vault_id="v1", relative_path="notes.md")
    assert len(chunks) == 1
    assert chunks[0].text == "Simple content without sections"
    assert chunks[0].file_id == "f1"
    assert chunks[0].relative_path == "notes.md"

def test_document_chunker_sections():
    chunker = DocumentChunker()
    doc = ParsedDocument(
        file_id="f2",
        path="course.pdf",
        title="Course",
        text="All course text",
        sections=[
            DocumentSection(heading="Chapter 1", text="Section 1 content about scheduling", page=1),
            DocumentSection(heading="Chapter 2", text="Section 2 content about deadlocks", page=2),
        ]
    )
    chunks = chunker.chunk(doc, vault_id="v1", relative_path="course.pdf")
    assert len(chunks) == 2
    assert chunks[0].heading == "Chapter 1"
    assert chunks[0].page == 1
    assert "scheduling" in chunks[0].text
    assert chunks[1].heading == "Chapter 2"
    assert chunks[1].page == 2
    assert "deadlocks" in chunks[1].text
