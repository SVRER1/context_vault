from datetime import datetime
from pathlib import Path

import pytest

from contextvault.core.config import AppConfig
from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.core.exceptions import PathSecurityError
from contextvault.retrieval.filesystem_models import RetrievalRequest
from contextvault.retrieval.filesystem_service import FilesystemRetrievalService
from contextvault.retrieval.filesystem_models import EvidencePassage
from contextvault.retrieval.evidence import EvidenceBuilder


class OfflineLLM:
    def is_available(self):
        return False


@pytest.fixture
def filesystem_vault(tmp_path):
    (tmp_path / "College" / "Java").mkdir(parents=True)
    (tmp_path / "College" / "DLCA").mkdir(parents=True)
    (tmp_path / "Projects" / "ContextVault").mkdir(parents=True)
    (tmp_path / "Generated").mkdir()
    (tmp_path / "College" / "Java" / "exceptions.md").write_text(
        "# Exception Handling\n\nJava exceptions are handled with try/catch blocks. "
        "Checked exceptions must be declared or caught.\n",
        encoding="utf-8",
    )
    (tmp_path / "College" / "Java" / "generics.md").write_text(
        "# Generics\n\nGenerics provide compile-time type safety.\n", encoding="utf-8"
    )
    (tmp_path / "College" / "DLCA" / "pipeline.md").write_text(
        "# Pipeline\n\nThis document discusses a hardware pipeline, not Java exceptions.\n",
        encoding="utf-8",
    )
    (tmp_path / "Projects" / "ContextVault" / "architecture.md").write_text(
        "# Architecture\n\nFilesystem-native retrieval surveys the selected directory and builds evidence.\n",
        encoding="utf-8",
    )
    (tmp_path / "Generated" / "secret.md").write_text(
        "# Generated secret\nThis must never be source evidence.\n", encoding="utf-8"
    )
    info = VaultInfo(
        id="filesystem-retrieval-vault",
        display_name="Filesystem Retrieval",
        absolute_path=str(tmp_path),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
    )
    return Vault(info), tmp_path


def test_scoped_retrieval_constructs_evidence_without_index(filesystem_vault, tmp_path):
    vault, _ = filesystem_vault
    service = FilesystemRetrievalService(
        vault,
        llm_client=OfflineLLM(),
        config=AppConfig(app_data_dir=str(tmp_path / "app-data")),
    )
    request = RetrievalRequest(
        query="What does the material say about exception handling?",
        vault_id=vault.vault_id,
        source_scope="College/Java",
    )

    evidence = service.retrieve(request)

    assert evidence.sufficient is True
    assert "exceptions.md" in evidence.markdown
    assert "try/catch" in evidence.markdown
    assert "DLCA" not in evidence.markdown
    assert "Projects" not in evidence.markdown
    assert Path(evidence.runtime_dir, "evidence.md").exists()
    assert Path(evidence.runtime_dir, "sources.json").exists()


def test_scope_switches_without_reindexing(filesystem_vault, tmp_path):
    vault, _ = filesystem_vault
    service = FilesystemRetrievalService(
        vault,
        llm_client=OfflineLLM(),
        config=AppConfig(app_data_dir=str(tmp_path / "app-data")),
    )

    first = service.search(RetrievalRequest(
        query="exception handling", vault_id=vault.vault_id, source_scope="College/Java", operation="search"
    ))
    second = service.search(RetrievalRequest(
        query="filesystem retrieval evidence", vault_id=vault.vault_id, source_scope="Projects/ContextVault", operation="search"
    ))

    assert [item.survey.relative_path for item in first] == ["College/Java/exceptions.md"]
    assert [item.survey.relative_path for item in second] == ["Projects/ContextVault/architecture.md"]


def test_scope_escape_and_generated_content_are_rejected(filesystem_vault, tmp_path):
    vault, _ = filesystem_vault
    service = FilesystemRetrievalService(
        vault,
        llm_client=OfflineLLM(),
        config=AppConfig(app_data_dir=str(tmp_path / "app-data")),
    )

    with pytest.raises(PathSecurityError):
        service.search(RetrievalRequest(
            query="pipeline", vault_id=vault.vault_id, source_scope="../College/DLCA", operation="search"
        ))
    with pytest.raises(ValueError):
        service.search(RetrievalRequest(
            query="secret", vault_id=vault.vault_id, source_scope="Generated", operation="search"
        ))

    results = service.search(RetrievalRequest(
        query="generated secret", vault_id=vault.vault_id, source_scope=None, operation="search"
    ))
    assert all(item.survey.relative_path != "Generated/secret.md" for item in results)


def test_large_file_uses_bounded_sampled_windows(filesystem_vault, tmp_path):
    vault, root = filesystem_vault
    large = root / "College" / "Java" / "large.md"
    large.write_text(("ordinary filler line\n" * 20000) + "needle exception handling at the end\n", encoding="utf-8")
    service = FilesystemRetrievalService(
        vault,
        llm_client=OfflineLLM(),
        config=AppConfig(app_data_dir=str(tmp_path / "app-data"), retrieval_preview_bytes=4096),
    )
    evidence = service.retrieve(RetrievalRequest(
        query="needle exception handling",
        vault_id=vault.vault_id,
        source_scope="College/Java",
        max_bytes_per_read=4096,
    ))

    assert evidence.sufficient is True
    assert "needle exception handling" in evidence.markdown
    large_passage = next(item for item in evidence.passages if item.relative_path.endswith("large.md"))
    assert len(large_passage.text.encode("utf-8")) <= 4096
    assert large_passage.extraction_method == "sampled-line-window"


def test_evidence_builder_deduplicates_and_rejects_out_of_scope_content(filesystem_vault, tmp_path):
    vault, _ = filesystem_vault
    builder = EvidenceBuilder(vault, AppConfig(app_data_dir=str(tmp_path / "app-data")))
    request = RetrievalRequest(
        query="exception handling", vault_id=vault.vault_id, source_scope="College/Java"
    )
    passage = EvidencePassage(
        evidence_id="one", relative_path="College/Java/exceptions.md", text="try/catch", reason="match"
    )
    duplicate = EvidencePassage(
        evidence_id="two", relative_path="College/Java/exceptions.md", text="try/catch", reason="same match"
    )
    sibling = EvidencePassage(
        evidence_id="three", relative_path="College/DLCA/pipeline.md", text="ignore", reason="out of scope"
    )
    evidence = builder.build(request, [passage, duplicate, sibling])

    assert len(evidence.passages) == 1
    assert "try/catch" in evidence.markdown
    assert "DLCA" not in evidence.markdown


def test_symlink_outside_vault_is_not_surveyed(filesystem_vault, tmp_path):
    vault, root = filesystem_vault
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("outside secret", encoding="utf-8")
    link = root / "College" / "Java" / "outside-link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable in this environment")

    service = FilesystemRetrievalService(
        vault, llm_client=OfflineLLM(), config=AppConfig(app_data_dir=str(tmp_path / "app-data"))
    )
    results = service.search(RetrievalRequest(
        query="outside secret", vault_id=vault.vault_id, source_scope="College/Java", operation="search"
    ))
    assert all(item.survey.relative_path != "College/Java/outside-link.txt" for item in results)
