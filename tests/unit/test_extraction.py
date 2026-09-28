from contextvault.core.models import DocumentSection, ParsedDocument
from contextvault.indexing.chunker import DocumentChunker
from contextvault.indexing.extraction import DocumentExtractor
from contextvault.parsers.plaintext import PlainTextParser
from contextvault.parsers.registry import ParserRegistry
from contextvault.core.config import AppConfig
from contextvault.core.vault import Vault
from contextvault.services.vault_service import VaultService
from contextvault.storage.database import Database


def test_normalized_extraction_preserves_heading_and_line_locations(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Retrieval\nFirst line.\nSecond line.\n\n## Ranking\nBM25 ranks results.\n", encoding="utf-8")

    result = DocumentExtractor().extract(path, "file-1")

    assert result.status == "ok"
    assert result.word_count > 0
    assert result.document.path == str(path)
    assert result.document.sections[0].heading == "Retrieval"
    assert result.document.sections[0].line_start == 1
    assert result.document.sections[0].char_start == 0
    chunks = DocumentChunker().chunk(result.document, vault_id="vault-1")
    assert chunks[0].heading == "Retrieval"
    assert chunks[0].line_start == 1
    assert chunks[0].char_start == 0


def test_extraction_reports_truncation(tmp_path, monkeypatch):
    path = tmp_path / "large.txt"
    path.write_text("0123456789abcdef", encoding="utf-8")
    monkeypatch.setattr(PlainTextParser, "MAX_SIZE", 8)

    result = DocumentExtractor().extract(path, "file-2")

    assert result.status == "truncated"
    assert result.bytes_read == 8
    assert result.document.text == "01234567"


def test_empty_and_unsupported_results_are_explicit(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n", encoding="utf-8")

    extractor = DocumentExtractor()
    assert extractor.extract(empty, "empty").status == "empty"
    assert extractor.extract(tmp_path / "archive.zip", "zip").status == "unsupported"


def test_extractor_converts_parser_exception_to_error(tmp_path):
    class BrokenParser:
        def supported_extensions(self):
            return {".bad"}

        def parse(self, path, file_id):
            raise ValueError("corrupt fixture")

    registry = ParserRegistry()
    registry.register(BrokenParser())
    result = DocumentExtractor(registry).extract(tmp_path / "broken.bad", "bad")

    assert result.status == "error"
    assert "corrupt fixture" in result.error


def test_chunking_carries_page_slide_sheet_and_range_locations():
    doc = ParsedDocument(
        file_id="file-3",
        text="page text\n\nslide text\n\nsheet text",
        sections=[
            DocumentSection(text="page text", page=3, heading="Evidence", line_start=4, line_end=4),
            DocumentSection(text="slide text", slide=2),
            DocumentSection(text="sheet text", sheet="Data", cell_range="A1:B2"),
        ],
    )

    chunks = DocumentChunker().chunk(doc)
    assert (chunks[0].page, chunks[0].heading, chunks[0].line_start) == (3, "Evidence", 4)
    assert chunks[1].slide == 2
    assert chunks[2].sheet == "Data"
    assert chunks[2].cell_range == "A1:B2"


def test_default_extraction_registry_does_not_enable_provider_ocr():
    extractor = DocumentExtractor()
    image_parser = extractor.registry.get_parser(".png")
    assert image_parser.ocr_client is None


def test_vault_index_uses_normalized_results_and_populates_fts(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "retrieval.md").write_text("# Retrieval\nVector database evidence.", encoding="utf-8")
    config = AppConfig(app_data_dir=str(tmp_path / "app-data"))
    app_db = Database(config.app_db_path)
    app_db.initialize()
    service = VaultService(config, app_db)
    info = service.registry.register_vault(source, "source")
    vault = Vault(info)
    vault_db = service.get_vault_db(vault)

    class ForbiddenOCR:
        def ocr_image(self, path):
            raise AssertionError("normal indexing must not invoke optional provider OCR")

    stats = service.index_vault(vault, vault_db, ocr_client=ForbiddenOCR())

    file_row = vault_db.fetch_one("SELECT extract_status, word_count FROM files WHERE filename = 'retrieval.md'")
    assert stats["parsed"] == 1
    assert file_row["extract_status"] == "ok"
    assert file_row["word_count"] >= 4
    assert vault_db.fetch_one("SELECT id FROM chunks_fts WHERE text MATCH 'vector'") is not None
    vault_db.close()
    app_db.close()
