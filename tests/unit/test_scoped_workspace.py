from datetime import datetime

import pytest

from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.core.exceptions import PathSecurityError
from contextvault.filesystem.operations import FileOperations
from contextvault.generation.generator import ContentGenerator
from contextvault.indexing.scanner import FileScanner
from contextvault.organisation.rules import OrganisationRules
from contextvault.services.organisation_service import OrganisationService
from contextvault.storage.database import Database


def _make_vault(tmp_path):
    root = tmp_path / "vault"
    (root / "Alpha").mkdir(parents=True)
    (root / "Beta").mkdir()
    (root / "Alpha" / "alpha.txt").write_text("alpha source", encoding="utf-8")
    (root / "Beta" / "beta.txt").write_text("beta source", encoding="utf-8")
    info = VaultInfo(
        id="scoped-vault",
        display_name="Scoped Vault",
        absolute_path=str(root),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
    )
    vault = Vault(info)
    db = Database(tmp_path / "index.db")
    db.initialize()
    db.execute(
        "INSERT INTO vaults (id, display_name, absolute_path, created_at, last_opened_at) VALUES (?, ?, ?, ?, ?)",
        (info.id, info.display_name, info.absolute_path, info.created_at.isoformat(), info.last_opened_at.isoformat()),
    )
    db.conn.commit()
    FileScanner(vault, db).scan()
    return vault, db


def test_scope_is_contained_and_rejects_escape(tmp_path):
    vault, _ = _make_vault(tmp_path)
    assert vault.scope_relative_path("Alpha") == "Alpha"
    assert vault.is_in_scope("Alpha/alpha.txt", "Alpha")
    assert not vault.is_in_scope("Beta/beta.txt", "Alpha")
    with pytest.raises(PathSecurityError):
        vault.scope_root("../Beta")


def test_organisation_preview_stays_inside_selected_scope(tmp_path):
    vault, db = _make_vault(tmp_path)
    service = OrganisationService(vault, db, llm_client=None, retriever=None)
    plan = service.preview(
        OrganisationRules(strategy="deterministic", primary_grouping="file-family"),
        subfolder="Alpha",
    )
    assert plan.source_scope == "Alpha"
    assert len(plan.operations) == 1
    assert plan.operations[0].source.replace("\\", "/") == "Alpha/alpha.txt"
    assert plan.operations[0].destination.replace("\\", "/") == "Alpha/Documents/alpha.txt"
    assert all(op.destination.startswith("Alpha/") for op in plan.operations)


def test_generated_asset_records_selected_source_scope(tmp_path):
    vault, db = _make_vault(tmp_path)

    class EmptyRetriever:
        def retrieve(self, **kwargs):
            self.kwargs = kwargs
            return []

    retriever = EmptyRetriever()
    asset = ContentGenerator(None, retriever, vault, db, subfolder="Alpha").generate("summary")
    assert asset.source_scope == "Alpha"
    assert retriever.kwargs["subfolder"] == "Alpha"
    assert (vault.root_path / asset.relative_path).exists()
