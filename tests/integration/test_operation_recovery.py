"""Filesystem fault injection across the reviewed operation pipeline."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.filesystem import execution_service as execution_module
from contextvault.filesystem.execution_service import ExecutionService
from contextvault.filesystem.plan_service import PlanService
from contextvault.filesystem.recovery import RecoveryService
from contextvault.query.parser import parse_query
from contextvault.storage.database import Database


class InjectedCrash(BaseException):
    pass


def make_context(tmp_path):
    root = tmp_path / "vault"
    (root / "Docs").mkdir(parents=True)
    info = VaultInfo(id="fault-vault", display_name="Fault Vault", absolute_path=str(root),
                     created_at=datetime.now(), last_opened_at=datetime.now())
    vault = Vault(info)
    db = Database(tmp_path / "index.db")
    db.initialize()
    db.execute("INSERT INTO vaults (id,display_name,absolute_path,created_at,last_opened_at) VALUES(?,?,?,?,?)",
                (info.id, info.display_name, info.absolute_path, info.created_at.isoformat(), info.last_opened_at.isoformat()))
    db.conn.commit()
    return root, vault, db


def make_plan(root, vault, db):
    (root / "Docs" / "one.txt").write_text("reliable bytes", encoding="utf-8")
    return PlanService(vault, db).preview_rule(parse_query("type:txt"), "Sorted")


def test_commit_time_destination_race_never_overwrites(tmp_path, monkeypatch):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "one.txt"
    plan = make_plan(root, vault, db)
    destination = root / "Sorted" / "one.txt"
    original_publish = execution_module.publish_no_replace

    def race_publish(src, dst):
        destination.write_bytes(b"unrelated destination bytes")
        return original_publish(src, dst)

    monkeypatch.setattr(execution_module, "publish_no_replace", race_publish)
    result = ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)
    assert result.status == "needs_recovery"
    assert source.read_bytes() == b"reliable bytes"
    assert destination.read_bytes() == b"unrelated destination bytes"
    assert RecoveryService(vault, db).inspect_batch(result.batch_id)[0].classification == "manual_review"
    db.close()


def test_journal_write_failure_happens_before_any_file_change(tmp_path, monkeypatch):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "one.txt"
    plan = make_plan(root, vault, db)
    original_execute = db.execute

    def fail_intent(sql, params=()):
        if "INSERT INTO operation_items_v3" in sql:
            raise OSError("simulated journal failure")
        return original_execute(sql, params)

    monkeypatch.setattr(db, "execute", fail_intent)
    with pytest.raises(OSError, match="journal failure"):
        ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)
    assert source.read_bytes() == b"reliable bytes"
    assert not (root / "Sorted").exists()
    assert db.fetch_one("SELECT batch_id FROM operation_batches_v3") is None
    db.close()


def test_disk_full_refuses_commit_before_journal_or_mutation(tmp_path, monkeypatch):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "one.txt"
    plan = make_plan(root, vault, db)
    monkeypatch.setattr(execution_module.shutil, "disk_usage", lambda *_: SimpleNamespace(free=0))
    with pytest.raises(OSError, match="Insufficient free space"):
        ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)
    assert source.exists()
    assert not (root / "Sorted").exists()
    assert db.fetch_one("SELECT batch_id FROM operation_batches_v3") is None
    db.close()


def test_destination_permission_denial_is_previewed_and_commit_refused(tmp_path, monkeypatch):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "one.txt"
    source.write_text("reliable bytes", encoding="utf-8")
    monkeypatch.setattr("contextvault.filesystem.plan_service.os.access", lambda *_args: False)
    plan = PlanService(vault, db).preview_rule(parse_query("type:txt"), "Sorted")
    assert any(issue.code == "destination_not_writable" for issue in plan.conflicts)
    with pytest.raises(RuntimeError, match="contains conflicts"):
        ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)
    assert source.read_bytes() == b"reliable bytes"
    assert not (root / "Sorted").exists()
    db.close()


def test_temp_checksum_mismatch_keeps_source_and_reports_recovery(tmp_path, monkeypatch):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "one.txt"
    plan = make_plan(root, vault, db)
    real_hash = execution_module.compute_sha256

    def mismatch_temp(path):
        if str(path).endswith(".tmp"):
            return "0" * 64
        return real_hash(path)

    monkeypatch.setattr(execution_module, "compute_sha256", mismatch_temp)
    result = ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)
    assert result.status == "needs_recovery"
    assert source.read_bytes() == b"reliable bytes"
    assert not (root / "Sorted" / "one.txt").exists()
    assert db.fetch_one("SELECT state FROM operation_items_v3 WHERE batch_id=?", (result.batch_id,))["state"] == "needs_recovery"
    db.close()


def test_locked_source_removal_retains_both_verified_copies_for_review(tmp_path, monkeypatch):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "one.txt"
    plan = make_plan(root, vault, db)
    original_unlink = type(source).unlink

    def locked_unlink(path, *args, **kwargs):
        if path == source:
            raise PermissionError("simulated locked source")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(type(source), "unlink", locked_unlink)
    result = ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)
    assert result.status == "needs_recovery"
    assert source.read_bytes() == b"reliable bytes"
    assert (root / "Sorted" / "one.txt").read_bytes() == b"reliable bytes"
    assessment = RecoveryService(vault, db).inspect_batch(result.batch_id)[0]
    assert assessment.classification == "manual_review"
    db.close()


def test_case_only_rename_uses_intermediate_and_preserves_file_id(tmp_path):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "Topic.txt"
    source.write_text("same bytes", encoding="utf-8")
    plan = PlanService(vault, db).preview_rename("Docs/Topic.txt", "topic.txt")
    assert plan.items[0].action == "rename"
    result = ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)
    assert result.status == "committed"
    assert (root / "Docs" / "topic.txt").read_text(encoding="utf-8") == "same bytes"
    assert [path.name for path in (root / "Docs").iterdir()] == ["topic.txt"]
    assert not list((root / "Docs").glob("*.rename"))
    row = db.fetch_one("SELECT relative_path FROM files WHERE id=?", (plan.items[0].file_id,))
    assert row["relative_path"] == "Docs/topic.txt"
    db.close()


def test_interrupted_case_rename_is_classified_and_recovered(tmp_path, monkeypatch):
    root, vault, db = make_context(tmp_path)
    source = root / "Docs" / "Topic.txt"
    source.write_text("same bytes", encoding="utf-8")
    plan = PlanService(vault, db).preview_rename("Docs/Topic.txt", "topic.txt")
    monkeypatch.setattr(execution_module, "publish_no_replace", lambda *_: (_ for _ in ()).throw(InjectedCrash()))
    with pytest.raises(InjectedCrash):
        ExecutionService(vault, db).commit(plan.plan_id, plan.digest, approved=True)

    monkeypatch.undo()
    batch = db.fetch_one("SELECT batch_id FROM operation_batches_v3")["batch_id"]
    recovery = RecoveryService(vault, db)
    assert recovery.inspect_batch(batch)[0].classification == "safe_to_finalize"
    result = recovery.recover(batch, approved=True)
    assert result["status"] == "committed"
    assert [path.name for path in (root / "Docs").iterdir()] == ["topic.txt"]
    assert db.fetch_one("SELECT relative_path FROM files WHERE id=?", (plan.items[0].file_id,))["relative_path"] == "Docs/topic.txt"
    db.close()
