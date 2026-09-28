from contextvault.core.config import AppConfig
from contextvault.filesystem.undo import UndoManager
from contextvault.llm.ollama_client import OllamaClient
from contextvault.query.parser import parse_query
from contextvault.retrieval.search_models import SearchRequest
from contextvault.services.service_container import ServiceContainer


def test_fresh_vault_offline_index_route_journal_and_undo(tmp_path, monkeypatch):
    def no_model(*_args, **_kwargs):
        raise AssertionError("model availability must not be checked for deterministic workflows")

    monkeypatch.setattr(OllamaClient, "is_available", no_model)
    root = tmp_path / "vault"
    (root / "Course").mkdir(parents=True)
    source = root / "Course" / "retrieval.md"
    source.write_text("# Retrieval\nVector database indexing notes.", encoding="utf-8")
    (root / "Course" / "assignment.md").write_text("Vector database assignment.", encoding="utf-8")
    config = AppConfig(app_data_dir=str(tmp_path / "app-data"))
    container = ServiceContainer(config)
    vault = container.open_vault(root)

    query = parse_query('type:md AND content:"vector database" AND NOT content:assignment')
    response = container.search_service.search(SearchRequest(
        vault_id=vault.vault_id, rule=query, source_scope="Course"
    ))
    assert [hit.relative_path for hit in response.hits] == ["Course/retrieval.md"]
    original_hash = container.vault_db.fetch_one(
        "SELECT sha256 FROM files WHERE vault_id=? AND relative_path=?",
        (vault.vault_id, "Course/retrieval.md"),
    )["sha256"]
    schema_version = container.vault_db.fetch_one("PRAGMA user_version")["user_version"]
    assert schema_version == 5

    plan = container.plan_service.preview_rule(query, "Filed", scope="Course")
    assert [(item.source, item.destination) for item in plan.items] == [
        ("Course/retrieval.md", "Course/Filed/retrieval.md")
    ]
    assert source.exists()
    result = container.execution_service.commit(plan.plan_id, plan.digest, approved=True)
    assert result.status == "committed"
    filed = root / "Course" / "Filed" / "retrieval.md"
    assert filed.read_text(encoding="utf-8") == "# Retrieval\nVector database indexing notes."
    moved = container.vault_db.fetch_one(
        "SELECT id, sha256, relative_path FROM files WHERE vault_id=? AND relative_path=?",
        (vault.vault_id, "Course/Filed/retrieval.md"),
    )
    assert moved["sha256"] == original_hash
    assert container.vault_db.fetch_one(
        "SELECT 1 FROM chunks_fts WHERE relative_path=? AND chunks_fts MATCH 'indexing'",
        ("Course/Filed/retrieval.md",),
    )
    batch = container.audit_service.get_journal_history(vault, limit=1)[0]
    assert batch["batch_id"] == result.batch_id and batch["status"] == "committed"
    item_id = batch["items"][0]["item_id"]
    assert UndoManager(container.vault_db, vault).can_undo_journal_item(item_id)

    container.audit_service.undo_journal_item(item_id, vault, approved=True)
    restored = root / "Course" / "retrieval.md"
    assert restored.read_text(encoding="utf-8") == "# Retrieval\nVector database indexing notes."
    final_row = container.vault_db.fetch_one(
        "SELECT id, sha256, relative_path FROM files WHERE vault_id=? AND relative_path=?",
        (vault.vault_id, "Course/retrieval.md"),
    )
    assert final_row["id"] == moved["id"] and final_row["sha256"] == original_hash
    assert container._llm_checked is False
    container.close_vault()
    container.app_db.close()
