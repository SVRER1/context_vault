from datetime import datetime

import fitz

from contextvault.core.config import AppConfig
from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.query.parser import parse_query
from contextvault.retrieval.search_models import SearchRequest
from contextvault.retrieval.search_service import SearchService
from contextvault.retrieval.search_models import SearchResponse
from contextvault.services.rag_service import RAGService
from contextvault.storage.database import Database


def make_search_context(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    config = AppConfig(app_data_dir=str(tmp_path / "app-data"))
    app_db = Database(config.app_db_path)
    app_db.initialize()
    info = VaultInfo(
        id="search-vault", display_name="Search", absolute_path=str(root),
        created_at=datetime.now(), last_opened_at=datetime.now(),
    )
    vault = Vault(info)
    db = Database(config.vault_data_dir(info.id) / "index.db")
    db.initialize()
    db.execute(
        "INSERT INTO vaults(id,display_name,absolute_path,created_at,last_opened_at) VALUES(?,?,?,?,?)",
        (info.id, info.display_name, info.absolute_path, info.created_at.isoformat(), info.last_opened_at.isoformat()),
    )
    db.conn.commit()
    service = SearchService(vault, db, config)
    return root, vault, db, app_db, service


def close_context(db, app_db):
    db.close()
    app_db.close()


def test_late_pdf_page_and_late_text_match_return_located_snippets(tmp_path):
    root, vault, db, app_db, service = make_search_context(tmp_path)
    pdf = fitz.open()
    pdf.new_page().insert_text((40, 60), "An opening page with unrelated material.")
    pdf.new_page().insert_text((40, 60), "retrievalneedle on the second page.")
    pdf.save(root / "late.pdf")
    pdf.close()
    long_text = "\n".join([f"Opening line {line}." for line in range(30)] + ["addresssequence appears near the end."])
    (root / "late.txt").write_text(long_text, encoding="utf-8")

    pdf_result = service.search(SearchRequest(vault_id=vault.vault_id, query="retrievalneedle"))
    text_result = service.search(SearchRequest(vault_id=vault.vault_id, query="addresssequence"))

    assert pdf_result.hits[0].passages[0].page == 2
    assert "retrievalneedle" in pdf_result.hits[0].passages[0].snippet
    assert "addresssequence" in text_result.hits[0].passages[0].snippet
    assert "Opening line 0." not in text_result.hits[0].passages[0].snippet
    close_context(db, app_db)


def test_quoted_phrase_requires_adjacency_and_unquoted_terms_rank_separately(tmp_path):
    root, vault, db, app_db, service = make_search_context(tmp_path)
    (root / "phrase.md").write_text("vector database supports retrieval", encoding="utf-8")
    (root / "apart.md").write_text("vector models and database systems", encoding="utf-8")

    phrase = service.search(SearchRequest(vault_id=vault.vault_id, query='"vector database"'))
    terms = service.search(SearchRequest(vault_id=vault.vault_id, query="vector database"))

    assert {hit.filename for hit in phrase.hits} == {"phrase.md"}
    assert {hit.filename for hit in terms.hits} == {"phrase.md", "apart.md"}
    close_context(db, app_db)


def test_filename_and_heading_matches_are_boosted_and_results_are_stable(tmp_path):
    root, vault, db, app_db, service = make_search_context(tmp_path)
    (root / "retrieval-notes.md").write_text("# Topic\nA shared body passage.", encoding="utf-8")
    (root / "ordinary.md").write_text("# Retrieval\nA shared body passage.", encoding="utf-8")

    request = SearchRequest(vault_id=vault.vault_id, query="retrieval")
    first = service.search(request)
    second = service.search(request)
    hits = {hit.filename: hit for hit in first.hits}

    assert hits["retrieval-notes.md"].matched_fields == ("filename",)
    assert "heading" in hits["ordinary.md"].matched_fields
    assert first.hits == second.hits
    assert [hit.file_id for hit in first.hits] == [hit.file_id for hit in second.hits]
    assert hits["retrieval-notes.md"].score > hits["ordinary.md"].score
    close_context(db, app_db)


def test_no_match_stale_edit_and_scope_are_handled_by_reconciliation(tmp_path):
    root, vault, db, app_db, service = make_search_context(tmp_path)
    (root / "inside").mkdir()
    (root / "inside" / "edit.md").write_text("oldneedle body", encoding="utf-8")
    (root / "outside").mkdir()
    (root / "outside" / "private.md").write_text("scopedneedle body", encoding="utf-8")

    first = service.search(SearchRequest(vault_id=vault.vault_id, query="oldneedle", source_scope="inside"))
    (root / "inside" / "edit.md").write_text("newneedle body", encoding="utf-8")
    updated = service.search(SearchRequest(vault_id=vault.vault_id, query="newneedle", source_scope="inside"))
    stale = service.search(SearchRequest(vault_id=vault.vault_id, query="oldneedle", source_scope="inside"))
    no_match = service.search(SearchRequest(vault_id=vault.vault_id, query="nosuchtoken"))
    outside = service.search(SearchRequest(vault_id=vault.vault_id, query="scopedneedle", source_scope="inside"))

    assert len(first.hits) == 1
    assert len(updated.hits) == 1
    assert updated.hits[0].file_id == first.hits[0].file_id
    assert stale.hits == ()
    assert no_match.hits == ()
    assert outside.hits == ()
    close_context(db, app_db)


def test_ast_filter_and_offline_rag_return_real_ids_and_evidence(tmp_path):
    root, vault, db, app_db, service = make_search_context(tmp_path)
    (root / "alpha.md").write_text("# Sequencing\nAddress sequencing is documented here.", encoding="utf-8")
    (root / "beta.md").write_text("Address sequencing assignment.", encoding="utf-8")

    response = service.search(SearchRequest(
        vault_id=vault.vault_id,
        query="address sequencing",
        rule=parse_query("extension:md AND NOT content:assignment"),
    ))
    rag = RAGService(vault=vault, search_service=service)
    answer = rag.ask("address sequencing", vault.vault_id)

    assert len(response.hits) == 1
    assert response.hits[0].file_id
    assert response.hits[0].passages[0].line_start is not None
    assert {source.file_path for source in answer.sources} == {"alpha.md", "beta.md"}
    assert "Address sequencing" in answer.answer
    assert rag.llm_client is None
    close_context(db, app_db)


def test_cli_where_compiles_to_shared_ast_without_rag_or_llm(monkeypatch):
    from types import SimpleNamespace
    import cli.main as cli_main

    class SearchStub:
        request = None

        def search(self, request):
            self.request = request
            return SearchResponse(hits=())

    search_stub = SearchStub()
    vault = SimpleNamespace(vault_id="cli-vault")
    container = SimpleNamespace(vault=vault, search_service=search_stub)
    monkeypatch.setattr(cli_main, "_require_active_vault", lambda: (container, vault))

    cli_main.search(
        query="vector database",
        scope=None,
        where='type:pdf AND NOT content:"assignment"',
        limit=15,
    )

    assert search_stub.request.query == "vector database"
    assert search_stub.request.rule == parse_query('type:pdf AND NOT content:"assignment"')
    assert search_stub.request.limit == 15
