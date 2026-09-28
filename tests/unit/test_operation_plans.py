from datetime import datetime

from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.filesystem.plan_models import RouteEntry, RouteSpec
from contextvault.filesystem.plan_service import PlanService
from contextvault.query.parser import parse_query
from contextvault.storage.database import Database


def make_context(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "A").mkdir()
    (root / "B").mkdir()
    info = VaultInfo(
        id="plan-vault", display_name="Plans", absolute_path=str(root),
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
    return root, vault, db, PlanService(vault, db)


def test_preview_is_persisted_reconstructible_and_does_not_mutate(tmp_path):
    root, _vault, db, service = make_context(tmp_path)
    (root / "A" / "one.txt").write_text("vector retrieval", encoding="utf-8")
    plan = service.preview_rule(parse_query("content:vector"), "Collected")

    assert len(plan.items) == 1
    assert plan.items[0].source == "A/one.txt"
    assert plan.items[0].destination == "Collected/one.txt"
    assert not (root / "Collected").exists()
    restored = service.get_plan(plan.plan_id)
    assert restored.digest == plan.digest
    assert restored.items == plan.items
    db.close()


def test_batch_destinations_detect_existing_and_casefold_collisions(tmp_path):
    root, _vault, db, service = make_context(tmp_path)
    (root / "A" / "same.txt").write_text("alpha", encoding="utf-8")
    (root / "B" / "same.txt").write_text("beta", encoding="utf-8")
    (root / "Collected").mkdir()
    (root / "Collected" / "same.txt").write_text("existing", encoding="utf-8")

    plan = service.preview_rule(parse_query("type:txt"), "Collected")
    codes = {issue.code for issue in plan.conflicts}
    assert "destination_exists" in codes
    assert "duplicate_planned_destination" in codes
    assert len(plan.items) == 2
    db.close()


def test_route_first_match_and_scope_are_shared_and_safe(tmp_path):
    root, _vault, db, service = make_context(tmp_path)
    (root / "A" / "one.txt").write_text("vector", encoding="utf-8")
    (root / "B" / "two.txt").write_text("vector", encoding="utf-8")
    route = RouteSpec(
        entries=(RouteEntry(parse_query("content:vector"), "Sorted"),),
        fallback="keep",
    )

    plan = service.preview_route(route, scope="A")
    assert [(item.source, item.destination) for item in plan.items] == [
        ("A/one.txt", "A/Sorted/one.txt")
    ]
    assert all(item.destination.startswith("A/") for item in plan.items)
    db.close()


def test_invalid_destination_name_is_a_preview_conflict(tmp_path):
    root, _vault, db, service = make_context(tmp_path)
    (root / "A" / "one.txt").write_text("vector", encoding="utf-8")

    plan = service.preview_rule(parse_query("content:vector"), "CON")
    assert any(issue.code == "reserved_destination_name" for issue in plan.conflicts)
    assert not (root / "CON").exists()
    db.close()
