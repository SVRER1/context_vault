import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from contextvault.query.ast import serialize
from contextvault.query.parser import parse_query
from contextvault.retrieval.search_models import PassageHit, SearchHit, SearchResponse
from desktop.pages.search_page import SearchPage
from desktop.widgets.rule_builder import RuleBuilder


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def test_visual_rule_builder_emits_same_ast_as_cli(qapp):
    builder = RuleBuilder()
    first = builder.add_condition("extension", "eq", "pdf")
    second = builder.add_condition("content", "phrase", "vector database")
    rule = builder.build_rule()
    assert serialize(rule) == serialize(parse_query('type:pdf AND content:"vector database"'))
    group = builder.add_group()
    group[1].setCurrentIndex(1)
    group[2].setChecked(True)
    add_group_condition = group[0].findChildren(QPushButton)[0]
    for term in ("retrieval", "assignment"):
        add_group_condition.click()
        _, field, op, value = group[3][-1]
        field.setCurrentText("content")
        op.setCurrentText("contains")
        value.setText(term)
    assert serialize(builder.build_rule()) == serialize(
        parse_query('type:pdf AND content:"vector database" AND NOT (content:retrieval OR content:assignment)')
    )


def test_search_page_renders_ranked_passage_location_and_absolute_path(qapp, tmp_path):
    class Container:
        vault = None

    class Context:
        service_container = Container()
        active_subfolder = None

    page = SearchPage(Context())
    hit = SearchHit(
        file_id="file-1", absolute_path=str(tmp_path / "notes.md"), relative_path="notes.md",
        filename="notes.md", extension=".md", mime_type="text/markdown", size=12,
        modified=1.0, score=0.7, matched_fields=("content",),
        passages=(PassageHit("chunk-1", "vector database notes", 0.7, line_start=4, line_end=6),),
        extract_status="ok", content_complete=True,
    )
    page.handle_results(SearchResponse((hit,)))
    rendered = page.results_list.item(0).text()
    assert "notes.md" in rendered and "Lines 4-6" in rendered and "vector database" in rendered
    assert page.results_list.item(0).data(256) == str(tmp_path / "notes.md")
