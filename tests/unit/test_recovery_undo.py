from datetime import datetime

from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.filesystem.execution_service import ExecutionService
from contextvault.filesystem.plan_models import RouteEntry, RouteSpec
from contextvault.filesystem.plan_service import PlanService
from contextvault.filesystem.recovery import RecoveryService
from contextvault.filesystem.undo import UndoManager
from contextvault.query.parser import parse_query
from contextvault.storage.database import Database


def make_context(tmp_path):
    root = tmp_path / "vault"
    root.mkdir(parents=True)
    (root / "Docs").mkdir()
    info = VaultInfo(id="history-vault", display_name="History", absolute_path=str(root),
                     created_at=datetime.now(), last_opened_at=datetime.now())
    vault = Vault(info)
    db = Database(tmp_path / "index.db")
    db.initialize()
    db.execute("INSERT INTO vaults (id,display_name,absolute_path,created_at,last_opened_at) VALUES(?,?,?,?,?)",
                (info.id, info.display_name, info.absolute_path, info.created_at.isoformat(), info.last_opened_at.isoformat()))
    db.conn.commit()
    return root, vault, db


def plan_move(root, vault, db, action="move"):
    (root / "Docs" / "one.txt").write_text("journaled bytes", encoding="utf-8")
    route = RouteSpec((RouteEntry(parse_query("type:txt"), "Sorted", action),), fallback="keep")
    return PlanService(vault, db).preview_route(route)


def test_recovery_finalizes_verified_destination_after_index_failure(tmp_path, monkeypatch):
    root, vault, db = make_context(tmp_path)
    plan = plan_move(root, vault, db)
    executor = ExecutionService(vault, db)
    monkeypatch.setattr(executor, "_update_index", lambda *_args: (_ for _ in ()).throw(RuntimeError("simulated crash")))
    result = executor.commit(plan.plan_id, plan.digest, approved=True)

    assert result.status == "needs_recovery"
    recovery = RecoveryService(vault, db)
    assessment = recovery.inspect_batch(result.batch_id)
    assert assessment[0].classification == "safe_to_finalize"
    fixed = recovery.recover(result.batch_id, approved=True)
    assert fixed["status"] == "committed"
    again = recovery.recover(result.batch_id, approved=True)
    assert again["status"] == "committed"
    assert db.fetch_one("SELECT relative_path FROM files WHERE id=?", (plan.items[0].file_id,))["relative_path"] == "Sorted/one.txt"
    db.close()


def test_journal_undo_requires_current_hash_and_free_original_path(tmp_path):
    root, vault, db = make_context(tmp_path)
    plan = plan_move(root, vault, db)
    result = ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)
    item = db.fetch_one("SELECT item_id FROM operation_items_v3 WHERE batch_id=?", (result.batch_id,))["item_id"]
    manager = UndoManager(db, vault)

    assert manager.can_undo_journal_item(item)
    undone = manager.undo_journal_item(item, approved=True)
    assert undone["status"] == "undone"
    assert (root / "Docs" / "one.txt").read_text(encoding="utf-8") == "journaled bytes"
    assert not (root / "Sorted" / "one.txt").exists()
    assert not manager.can_undo_journal_item(item)
    db.close()


def test_copy_is_never_offered_for_undo_and_changed_move_is_refused(tmp_path):
    root, vault, db = make_context(tmp_path)
    copy_plan = plan_move(root, vault, db, action="copy")
    copied = ExecutionService(vault, db).commit(copy_plan.plan_id, copy_plan.digest, approved=True)
    copy_item = db.fetch_one("SELECT item_id FROM operation_items_v3 WHERE batch_id=?", (copied.batch_id,))["item_id"]
    manager = UndoManager(db, vault)
    assert not manager.can_undo_journal_item(copy_item)
    db.close()

    root, vault, db = make_context(tmp_path / "changed")
    move_plan = plan_move(root, vault, db)
    moved = ExecutionService(vault, db).commit(move_plan.plan_id, move_plan.digest, approved=True)
    move_item = db.fetch_one("SELECT item_id FROM operation_items_v3 WHERE batch_id=?", (moved.batch_id,))["item_id"]
    (root / "Sorted" / "one.txt").write_text("third party edit", encoding="utf-8")
    assert not UndoManager(db, vault).can_undo_journal_item(move_item)
    db.close()

    root, vault, db = make_context(tmp_path / "occupied")
    move_plan = plan_move(root, vault, db)
    moved = ExecutionService(vault, db).commit(move_plan.plan_id, move_plan.digest, approved=True)
    move_item = db.fetch_one("SELECT item_id FROM operation_items_v3 WHERE batch_id=?", (moved.batch_id,))["item_id"]
    (root / "Docs" / "one.txt").write_text("new unrelated file", encoding="utf-8")
    assert not UndoManager(db, vault).can_undo_journal_item(move_item)
    db.close()


def test_history_reports_batch_items_and_recovery_advice(tmp_path):
    root, vault, db = make_context(tmp_path)
    plan = plan_move(root, vault, db)
    result = ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)
    rows = RecoveryService(vault, db).history()
    assert rows[0]["batch_id"] == result.batch_id
    assert rows[0]["items"][0]["after_hash"]
    assert rows[0]["assessment"][0].classification == "complete"
    db.close()
