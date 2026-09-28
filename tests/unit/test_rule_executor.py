from contextvault.core.config import AppConfig
from contextvault.core.vault import Vault
from contextvault.indexing.index_service import IndexService
from contextvault.parsers.plaintext import PlainTextParser
from contextvault.query.ast import All, Any, Not, Predicate
from contextvault.query.executor import RuleExecutor
from contextvault.query.parser import parse_query
from contextvault.storage.database import Database
from contextvault.storage.index_repository import IndexRepository
from contextvault.services.vault_service import VaultService


def make_rule_context(tmp_path):
    root = tmp_path / "vault"
    (root / "CourseA").mkdir(parents=True)
    (root / "CourseB").mkdir()
    config = AppConfig(app_data_dir=str(tmp_path / "app-data"))
    app_db = Database(config.app_db_path)
    app_db.initialize()
    service = VaultService(config, app_db)
    info = service.registry.register_vault(root, "rules")
    vault = Vault(info)
    db = service.get_vault_db(vault)
    return root, config, vault, db, app_db, RuleExecutor(vault, db, config)


def close_context(db, app_db):
    db.close()
    app_db.close()


def test_boolean_content_phrase_and_nested_evaluation(tmp_path):
    root, _config, _vault, db, app_db, executor = make_rule_context(tmp_path)
    (root / "CourseA" / "one.md").write_text("Vector database retrieval evidence.", encoding="utf-8")
    (root / "CourseA" / "two.md").write_text("Vector indexing without retrieval.", encoding="utf-8")
    (root / "CourseB" / "three.md").write_text("Operating systems assignment.", encoding="utf-8")

    result = executor.select(parse_query('content:"vector database" OR (content:retrieval AND NOT content:assignment)'))
    names = {db.get_file_by_id(file_id)["filename"] for file_id in result.matched_ids}

    assert names == {"one.md", "two.md"}
    assert result.unknown_ids == ()
    assert result.index_run_id
    close_context(db, app_db)


def test_metadata_range_tags_hash_and_scope_are_parameterized(tmp_path):
    root, _config, vault, db, app_db, executor = make_rule_context(tmp_path)
    file_a = root / "CourseA" / "alpha.pdf"
    file_a.write_text("retrieval", encoding="utf-8")
    (root / "CourseB" / "beta.pdf").write_text("retrieval", encoding="utf-8")
    (root / "CourseA" / "notes.md").write_text("unrelated", encoding="utf-8")
    IndexService(vault, db, _config).reconcile()
    row = db.fetch_one("SELECT id, sha256, size FROM files WHERE filename='alpha.pdf'")
    IndexRepository(db).add_tag(row["id"], "Course Work")
    db.conn.commit()

    result = executor.select(
        parse_query(f'extension:pdf AND size>={row["size"]}B AND tag:"course work" AND hash:{row["sha256"]}'),
        scope="CourseA",
    )

    assert result.matched_ids == (row["id"],)
    assert not result.unknown_ids
    close_context(db, app_db)


def test_incomplete_content_is_unknown_under_not_and_negative_term(tmp_path, monkeypatch):
    root, _config, _vault, db, app_db, executor = make_rule_context(tmp_path)
    (root / "CourseA" / "complete.md").write_text("ordinary complete notes", encoding="utf-8")
    IndexService(executor.vault, db, _config).reconcile()
    (root / "CourseA" / "unsupported.bin").write_bytes(b"x")
    truncated = root / "CourseA" / "truncated.txt"
    truncated.write_text("prefix and hidden tail", encoding="utf-8")
    monkeypatch.setattr(PlainTextParser, "MAX_SIZE", 6)

    result = executor.select(parse_query("NOT content:assignment"))
    matched = {db.get_file_by_id(file_id)["filename"] for file_id in result.matched_ids}
    unknown = {db.get_file_by_id(file_id)["filename"] for file_id in result.unknown_ids}

    assert matched == {"complete.md"}
    assert unknown == {"unsupported.bin", "truncated.txt"}
    assert {db.get_file_by_id(file_id)["filename"] for file_id in result.excluded_ids} == set()
    close_context(db, app_db)


def test_content_match_in_truncated_file_is_positive_evidence(tmp_path, monkeypatch):
    root, _config, _vault, db, app_db, executor = make_rule_context(tmp_path)
    path = root / "CourseA" / "short.txt"
    path.write_text("needle and a much longer tail", encoding="utf-8")
    monkeypatch.setattr(PlainTextParser, "MAX_SIZE", 16)

    result = executor.select(parse_query("content:needle"))

    assert len(result.matched_ids) == 1
    assert result.unknown_ids == ()
    close_context(db, app_db)


def test_regex_candidate_bound_reports_unchecked_ids_as_unknown(tmp_path):
    root, _config, _vault, db, app_db, executor = make_rule_context(tmp_path)
    for filename in ("alpha.txt", "beta.txt", "gamma.txt"):
        (root / "CourseA" / filename).write_text("content", encoding="utf-8")

    result = executor.select(parse_query('name~".*a.*"'), candidate_limit=1)

    assert len(result.matched_ids) <= 1
    assert len(result.unknown_ids) == 2
    assert any("candidate limit" in message for message in result.diagnostics)
    close_context(db, app_db)


def test_malicious_fts_syntax_is_literal_and_cannot_escape_scope(tmp_path):
    root, _config, _vault, db, app_db, executor = make_rule_context(tmp_path)
    (root / "CourseA" / "safe.md").write_text("ordinary safe passage", encoding="utf-8")
    (root / "CourseB" / "private.md").write_text("secretmatch passage", encoding="utf-8")

    result = executor.select(parse_query('content:"secretmatch OR *"'), scope="CourseA")

    assert result.matched_ids == ()
    assert result.unknown_ids == ()
    assert len(result.excluded_ids) == 1
    close_context(db, app_db)


def test_failed_reconcile_fails_closed_to_unknown(tmp_path, monkeypatch):
    root, _config, _vault, db, app_db, executor = make_rule_context(tmp_path)
    (root / "CourseA" / "kept.md").write_text("visible source", encoding="utf-8")
    IndexService(executor.vault, db, _config).reconcile()
    (root / "CourseA" / "new.md").write_text("new unindexed source", encoding="utf-8")
    monkeypatch.setattr(IndexService, "_discover", lambda _self, _root: (_ for _ in ()).throw(PermissionError("fixture")))

    result = executor.select(parse_query("name:kept"))

    assert result.matched_ids == ()
    assert len(result.unknown_ids) == 1
    assert any("failed" in message for message in result.diagnostics)
    close_context(db, app_db)
