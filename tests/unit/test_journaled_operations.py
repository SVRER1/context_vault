from datetime import datetime

import pytest

from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.filesystem.execution_service import ExecutionService, StaleOperationPlanError
from contextvault.filesystem.plan_models import RouteEntry, RouteSpec
from contextvault.filesystem.plan_service import PlanService
from contextvault.query.parser import parse_query
from contextvault.storage.database import Database


def make_context(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Docs").mkdir()
    info = VaultInfo(
        id="journal-vault", display_name="Journal", absolute_path=str(root),
        created_at=datetime.now(), last_opened_at=datetime.now(),
    )
    vault = Vault(info)
    db = Database(tmp_path / "index.db")
    db.initialize()
    db.execute(
        "INSERT INTO vaults (id,display_name,absolute_path,created_at,last_opened_at) VALUES (?,?,?,?,?)",
        (info.id, info.display_name, info.absolute_path, info.created_at.isoformat(), info.last_opened_at.isoformat()),
    )
    db.conn.commit()
    return root, vault, db


def make_plan(root, vault, db, *, action="move"):
    service = PlanService(vault, db)
    route = RouteSpec(
        entries=(RouteEntry(parse_query("type:txt"), "Sorted", action),),
        fallback="keep",
    )
    return service.preview_route(route)


def test_move_commit_journals_before_mutation_and_updates_index(tmp_path):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "notes.txt"
    source.write_text("verifiable evidence", encoding="utf-8")
    plan = make_plan(root, vault, db)
    result = ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)

    destination = root / "Sorted" / "notes.txt"
    assert result.status == "committed", result.error
    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "verifiable evidence"
    row = db.fetch_one("SELECT relative_path FROM files WHERE id=?", (plan.items[0].file_id,))
    assert row["relative_path"] == "Sorted/notes.txt"
    assert db.fetch_one("SELECT state FROM operation_items_v3 WHERE batch_id=?", (result.batch_id,))["state"] == "committed"
    db.close()


def test_stale_plan_fails_before_mutation_and_records_no_batch(tmp_path):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "notes.txt"
    source.write_text("before", encoding="utf-8")
    plan = make_plan(root, vault, db)
    source.write_text("changed after preview", encoding="utf-8")

    with pytest.raises(StaleOperationPlanError, match="changed since preview"):
        ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)
    assert source.exists()
    assert not (root / "Sorted" / "notes.txt").exists()
    assert db.fetch_one("SELECT batch_id FROM operation_batches_v3") is None
    db.close()


def test_copy_keeps_source_and_adds_indexed_destination(tmp_path):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "notes.txt"
    source.write_text("copyable passage", encoding="utf-8")
    plan = make_plan(root, vault, db, action="copy")
    result = ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)

    assert result.status == "committed", result.error
    assert source.exists()
    assert (root / "Sorted" / "notes.txt").exists()
    copied = db.fetch_one("SELECT id FROM files WHERE relative_path='Sorted/notes.txt'")
    assert copied and copied["id"] != plan.items[0].file_id
    journal = db.fetch_one("SELECT result_file_id FROM operation_items_v3 WHERE batch_id=?", (result.batch_id,))
    assert journal["result_file_id"] == copied["id"]
    db.close()
