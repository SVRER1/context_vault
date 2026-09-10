from datetime import datetime

from contextvault.core.config import AppConfig
from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.retrieval.filesystem_models import RetrievalRequest
from contextvault.retrieval.filesystem_service import FilesystemRetrievalService


class OfflineLLM:
    def is_available(self):
        return False


def _vault(path, vault_id):
    return Vault(VaultInfo(
        id=vault_id,
        display_name=vault_id,
        absolute_path=str(path),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
    ))


def test_filesystem_retrieval_isolates_vaults_and_does_not_need_index(tmp_path):
    first_dir = tmp_path / "vault_a"
    second_dir = tmp_path / "vault_b"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "reactor.txt").write_text("The spaceship uses a cobalt reactor.", encoding="utf-8")
    (second_dir / "battery.txt").write_text("The spaceship uses a lithium battery.", encoding="utf-8")

    vault_a = _vault(first_dir, "vault-a")
    service = FilesystemRetrievalService(
        vault_a,
        llm_client=OfflineLLM(),
        config=AppConfig(app_data_dir=str(tmp_path / "app-data")),
    )
    results = service.search(RetrievalRequest(
        query="spaceship reactor", vault_id="vault-a", operation="search"
    ))
    lithium = service.search(RetrievalRequest(
        query="lithium battery", vault_id="vault-a", operation="search"
    ))

    assert [result.survey.relative_path for result in results] == ["reactor.txt"]
    assert lithium == []
    assert vault_a.root_path == first_dir.resolve()
    assert vault_a.root_path != second_dir.resolve()

