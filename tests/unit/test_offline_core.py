from contextvault.core.config import AppConfig
from contextvault.filesystem.undo import UndoManager
from contextvault.query.parser import parse_query
from contextvault.retrieval.search_models import SearchRequest
from contextvault.services.rag_service import RAGService
from contextvault.services.service_container import ServiceContainer


def test_open_index_search_rules_plan_commit_and_undo_do_not_probe_ollama(tmp_path, monkeypatch):
    from contextvault.llm.ollama_client import OllamaClient

    def forbidden(*_args, **_kwargs):
        raise AssertionError("deterministic core attempted an Ollama availability check")

    monkeypatch.setattr(OllamaClient, "is_available", forbidden)
    root = tmp_path / "vault"
    root.mkdir()
    (root / "notes.txt").write_text("deterministic retrieval evidence", encoding="utf-8")
    container = ServiceContainer(AppConfig(app_data_dir=str(tmp_path / "app-data")))
    vault = container.open_vault(str(root))

    hits = container.search_service.search(SearchRequest(vault_id=vault.vault_id, query="retrieval"))
    selected = container.rule_executor.select(parse_query("content:deterministic"))
    plan = container.plan_service.preview_rule(parse_query("content:retrieval"), "Filed")
    assert hits.hits and selected.matched_ids
    assert len(plan.items) == 1

    result = container.execution_service.commit(plan.plan_id, plan.digest, approved=True)
    item_id = container.vault_db.fetch_one(
        "SELECT item_id FROM operation_items_v3 WHERE batch_id=?", (result.batch_id,)
    )["item_id"]
    assert result.status == "committed"
    assert UndoManager(container.vault_db, vault).can_undo_journal_item(item_id)
    assert container.audit_service.get_journal_history(vault)
    from contextvault.filesystem.recovery import RecoveryService
    assert RecoveryService(vault, container.vault_db).inspect_incomplete() == []
    container.organisation_service.detect_duplicates()
    assert container.orchestrator is not None
    assert container.has_llm is False
    assert container._llm_checked is False
    container.close_vault()
    container.app_db.close()


def test_synthesis_provider_receives_only_retrieved_evidence(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "evidence.md").write_text("BM25 ranks lexical retrieval evidence.", encoding="utf-8")
    container = ServiceContainer(AppConfig(app_data_dir=str(tmp_path / "app-data")))
    active = container.open_vault(str(root))
    seen = []

    class FakeProvider:
        def generate(self, request):
            seen.append(request)
            return "Generated answer from evidence."

    service = RAGService(
        vault=active,
        search_service=container.search_service,
        retrieval_service=container.filesystem_retrieval_service,
        artifact_provider=FakeProvider(),
    )
    response = service.synthesize("How does BM25 rank retrieval?", active.vault_id)

    assert response.answer == "Generated answer from evidence."
    assert len(seen) == 1
    assert "BM25 ranks lexical retrieval evidence" in seen[0].evidence
    assert seen[0].source_scope is None
    assert response.sources
    assert container._llm_checked is False
    container.close_vault()
    container.app_db.close()


def test_ambiguous_intent_does_not_call_optional_classifier():
    from contextvault.agent.intent import IntentRouter

    class BombClient:
        def is_available(self):
            raise AssertionError("intent classification must stay deterministic")

    result = IntentRouter.classify("Could you explain the evidence in my files?", BombClient())
    assert result.intent == "rag_query"


def test_artifact_provider_checks_model_only_when_generation_is_requested():
    import pytest
    from contextvault.core.exceptions import OllamaUnavailableError
    from contextvault.generation.artifact_provider import ArtifactRequest, OllamaArtifactProvider

    calls = []

    class OfflineClient:
        def is_available(self):
            calls.append("availability")
            return False

    provider = OllamaArtifactProvider(lambda: (calls.append("construct") or OfflineClient()))
    assert calls == []
    assert provider.availability_checked is False
    with pytest.raises(OllamaUnavailableError, match="offline"):
        provider.generate(ArtifactRequest("summary", "prompt", "selected evidence"))
    assert calls == ["construct", "availability"]
