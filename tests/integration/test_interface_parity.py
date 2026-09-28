from datetime import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from contextvault.core.config import AppConfig
from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.filesystem.plan_service import PlanService
from contextvault.indexing.index_service import IndexService
from contextvault.query.parser import parse_query
from contextvault.retrieval.search_models import SearchRequest
from contextvault.retrieval.search_service import SearchService
from contextvault.storage.database import Database
from desktop.widgets.rule_builder import RuleBuilder


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_cli_and_visual_ast_share_selection_and_route_mappings(tmp_path, qapp):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "notes").mkdir()
    (root / "notes" / "rag.md").write_text("Vector database retrieval guide.", encoding="utf-8")
    (root / "notes" / "assignment.md").write_text("Vector database assignment.", encoding="utf-8")
    (root / "other.txt").write_text("Vector database retrieval guide.", encoding="utf-8")
    info = VaultInfo(id="parity", display_name="Parity", absolute_path=str(root),
                     created_at=datetime.now(), last_opened_at=datetime.now())
    vault = Vault(info)
    config = AppConfig(app_data_dir=str(tmp_path / "app-data"))
    db = Database(tmp_path / "index.db")
    db.initialize()
    db.execute(
        "INSERT INTO vaults (id,display_name,absolute_path,created_at,last_opened_at) VALUES (?,?,?,?,?)",
        (info.id, info.display_name, info.absolute_path, info.created_at.isoformat(), info.last_opened_at.isoformat()),
    )
    db.conn.commit()
    IndexService(vault, db, config).reconcile()

    gui = RuleBuilder()
    ext_row = gui.add_condition("extension", "eq", "md")
    gui.add_condition("content", "phrase", "vector database")
    group = gui.add_group()
    group[1].setCurrentIndex(1)
    group[2].setChecked(True)
    for term in ("assignment", "homework"):
        group[0].findChildren(QPushButton)[0].click()
        _, field, op, value = group[3][-1]
        field.setCurrentText("content")
        op.setCurrentText("contains")
        value.setText(term)
    gui_rule = gui.build_rule()
    cli_rule = parse_query('type:md AND content:"vector database" AND NOT (content:assignment OR content:homework)')

    search = SearchService(vault, db, config)
    cli_result = search.search(SearchRequest(info.id, rule=cli_rule, freshness_policy="cached"))
    gui_result = search.search(SearchRequest(info.id, rule=gui_rule, freshness_policy="cached"))
    assert [hit.relative_path for hit in gui_result.hits] == [hit.relative_path for hit in cli_result.hits] == ["notes/rag.md"]

    plans = PlanService(vault, db, config)
    cli_plan = plans.preview_rule(cli_rule, "Collected")
    gui_plan = plans.preview_rule(gui_rule, "Collected")
    assert [(item.source, item.destination) for item in gui_plan.items] == [
        (item.source, item.destination) for item in cli_plan.items
    ] == [("notes/rag.md", "Collected/rag.md")]
    db.close()
