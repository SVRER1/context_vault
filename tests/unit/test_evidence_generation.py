from datetime import datetime

from contextvault.core.config import AppConfig
from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.generation.generator import ContentGenerator
from contextvault.retrieval.filesystem_models import EvidenceDocument, EvidencePassage, RetrievalRequest
from contextvault.storage.database import Database


class FakeLLM:
    def is_available(self):
        return True

    def generate(self, prompt, **kwargs):
        assert "filesystem evidence" in prompt
        assert "source.md" in prompt
        return "A grounded artifact from the filesystem evidence."


class FakeRetrieval:
    def __init__(self, vault_id):
        self.vault_id = vault_id

    def retrieve(self, request: RetrievalRequest):
        return EvidenceDocument(
            request_id="retrieval-test",
            query=request.query,
            source_scope=request.source_scope,
            markdown=(
                "# Context Vault Query Evidence\n\n"
                "## Active Source Scope\nCourse\n\n"
                "## Evidence 1\nSource: `source.md`\n\n"
                "Relevant Evidence:\nfilesystem evidence\n"
            ),
            passages=[EvidencePassage(
                evidence_id="ev-source",
                relative_path="Course/source.md",
                text="filesystem evidence",
                reason="lexical match",
            )],
            runtime_dir="runtime-test",
            sufficient=True,
        )


def test_generation_uses_only_evidence_and_persists_source_provenance(tmp_path):
    (tmp_path / "Course").mkdir()
    (tmp_path / "Generated").mkdir()
    db = Database(tmp_path / "app.db")
    db.initialize()
    info = VaultInfo(
        id="evidence-generation-vault",
        display_name="Evidence Generation",
        absolute_path=str(tmp_path),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
    )
    db.execute(
        "INSERT INTO vaults (id, display_name, absolute_path, created_at, last_opened_at, file_count, chunk_count, index_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (info.id, info.display_name, info.absolute_path, info.created_at.isoformat(), info.last_opened_at.isoformat(), 0, 0, 1),
    )
    db.conn.commit()
    vault = Vault(info)
    generator = ContentGenerator(
        llm_client=FakeLLM(),
        retriever=None,
        retrieval_service=FakeRetrieval(vault.vault_id),
        vault=vault,
        db=db,
        subfolder="Course",
    )

    asset = generator.generate(asset_type="summary", topic="filesystem evidence")
    output = (vault.root_path / asset.relative_path).read_text(encoding="utf-8")

    assert asset.source_scope == "Course"
    assert asset.source_files == ["Course/source.md"]
    assert "source.md" in output
    assert (vault.root_path / asset.relative_path).parent == vault.generated_dir

