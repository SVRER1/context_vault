from datetime import datetime

from contextvault.core.config import AppConfig
from contextvault.core.models import VaultInfo
from contextvault.core.vault import Vault
from contextvault.indexing.index_service import IndexService
from contextvault.parsers.plaintext import PlainTextParser
from contextvault.query.ast import All, Any, Not, Predicate
from contextvault.query.executor import RuleExecutor
from contextvault.query.parser import parse_query
from contextvault.retrieval.search_models import SearchRequest
from contextvault.retrieval.search_service import SearchService
from contextvault.services.rag_service import RAGService
from contextvault.storage.database import Database


def make_vault(root, data_dir, vault_id):
    root.mkdir(parents=True, exist_ok=True)
    config = AppConfig(app_data_dir=str(data_dir))
    now = datetime.now()
    info = VaultInfo(
        id=vault_id, display_name=vault_id, absolute_path=str(root),
        created_at=now, last_opened_at=now,
    )
    vault = Vault(info)
    db = Database(config.vault_data_dir(vault_id) / "index.db")
    db.initialize()
    db.execute(
        "INSERT INTO vaults(id,display_name,absolute_path,created_at,last_opened_at) VALUES(?,?,?,?,?)",
        (info.id, info.display_name, info.absolute_path, now.isoformat(), now.isoformat()),
    )
    db.conn.commit()
    return config, vault, db


def test_text_and_gui_rules_share_vault_scope_and_search_truth(tmp_path, monkeypatch):
    data_dir = tmp_path / "app-data"
    root_a = tmp_path / "vault-a"
    root_b = tmp_path / "vault-b"
    (root_a / "CourseA").mkdir(parents=True)
    (root_a / "CourseB").mkdir()
    (root_a / "Generated").mkdir()
    (root_b / "CourseA").mkdir(parents=True)
    (root_a / "CourseA" / "target.md").write_text(
        "# Address sequencing\nAddress sequencing is discussed in this course note.", encoding="utf-8"
    )
    (root_a / "CourseB" / "assignment.md").write_text(
        "Address sequencing assignment material.", encoding="utf-8"
    )
    (root_a / "Generated" / "generated.md").write_text(
        "Address sequencing generated output.", encoding="utf-8"
    )
    (root_b / "CourseA" / "target.md").write_text(
        "Address sequencing from a separate vault.", encoding="utf-8"
    )
    config_a, vault_a, db_a = make_vault(root_a, data_dir, "vault-a-id")
    config_b, vault_b, db_b = make_vault(root_b, data_dir, "vault-b-id")
    service_a = SearchService(vault_a, db_a, config_a)
    service_b = SearchService(vault_b, db_b, config_b)

    text_rule = parse_query(
        '(extension:md OR extension:txt) AND content:"address sequencing" AND NOT content:assignment'
    )
    gui_rule = All((
        Any((Predicate("extension", "eq", ".md"), Predicate("extension", "eq", ".txt"))),
        Predicate("content", "phrase", "address sequencing"),
        Not(Predicate("content", "contains", "assignment")),
    ))

    selected_text = RuleExecutor(vault_a, db_a, config_a).select(text_rule, scope="CourseA")
    selected_gui = RuleExecutor(vault_a, db_a, config_a).select(gui_rule, scope="CourseA")
    search_a = service_a.search(SearchRequest(
        vault_id=vault_a.vault_id,
        query='"address sequencing"',
        rule=gui_rule,
        source_scope="CourseA",
    ))
    search_b = service_b.search(SearchRequest(
        vault_id=vault_b.vault_id,
        query='"address sequencing"',
        rule=text_rule,
        source_scope="CourseA",
    ))

    assert selected_text.matched_ids == selected_gui.matched_ids
    assert selected_text.unknown_ids == selected_gui.unknown_ids == ()
    assert len(selected_text.matched_ids) == 1
    id_a = selected_text.matched_ids[0]
    id_b = search_b.hits[0].file_id
    assert id_a != id_b
    assert search_a.hits[0].file_id == id_a
    assert search_a.hits[0].passages[0].heading == "Address sequencing"
    assert search_a.hits[0].passages[0].line_start == 1
    assert len(search_a.hits) == 1
    assert len(search_b.hits) == 1
    assert search_b.hits[0].file_id == id_b

    late_file = root_a / "CourseA" / "limited.txt"
    late_file.write_text("nothing useful beyond the first bytes", encoding="utf-8")
    monkeypatch.setattr(PlainTextParser, "MAX_SIZE", 5)
    partial = RuleExecutor(vault_a, db_a, config_a).select(text_rule, scope="CourseA")
    unknown_names = {db_a.get_file_by_id(file_id)["filename"] for file_id in partial.unknown_ids}

    assert unknown_names == {"limited.txt"}
    assert "Generated" not in {row["relative_path"].split("/")[0] for row in db_a.get_all_files(vault_a.vault_id)}
    rag = RAGService(vault=vault_a, search_service=service_a)
    offline = rag.ask("address sequencing", vault_a.vault_id, subfolder="CourseA")
    assert offline.sources
    assert all(source.file_path != "Generated/generated.md" for source in offline.sources)
    assert rag.llm_client is None

    db_a.close()
    db_b.close()
