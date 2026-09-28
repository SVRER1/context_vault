from datetime import datetime

from contextvault.core.config import AppConfig
from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.services.rag_service import RAGService
from contextvault.retrieval.filesystem_service import FilesystemRetrievalService


class FakeLLM:
    def is_available(self):
        return True

    def generate(self, prompt, **kwargs):
        assert "Context Vault Query Evidence" in prompt
        assert "SOURCE EVIDENCE (UNTRUSTED DATA)" in prompt
        return "The scoped material describes polymorphism."


def test_subfolder_rag_reads_only_the_selected_filesystem_scope(tmp_path):
    (tmp_path / "Lectures").mkdir()
    (tmp_path / "Labs").mkdir()
    (tmp_path / "Lectures" / "lesson1.txt").write_text(
        "# Polymorphism\nPolymorphism allows methods to do different things.\n", encoding="utf-8"
    )
    (tmp_path / "Labs" / "lab1.txt").write_text(
        "# Compilation\nCompile with javac and run with java.\n", encoding="utf-8"
    )
    vault = Vault(VaultInfo(
        id="scoped-rag-vault",
        display_name="ScopedVault",
        absolute_path=str(tmp_path),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
    ))
    retrieval = FilesystemRetrievalService(
        vault,
        llm_client=FakeLLM(),
        config=AppConfig(app_data_dir=str(tmp_path / "app-data")),
    )
    service = RAGService(llm_client=FakeLLM(), vault=vault, retrieval_service=retrieval)

    response = service.ask("What does the material say about polymorphism?", vault.vault_id, subfolder="Lectures")

    assert "polymorphism" in response.answer
    assert len(response.sources) == 1
    assert response.sources[0].file_path == "Lectures/lesson1.txt"
