import json
import re

from typer.testing import CliRunner

from contextvault.core.config import AppConfig
from contextvault.services.service_container import ServiceContainer
from cli import main as cli_main


runner = CliRunner()


def setup_cli(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    root.mkdir()
    source = root / "notes.txt"
    source.write_text("Vector database retrieval evidence.", encoding="utf-8")
    config = AppConfig(app_data_dir=str(tmp_path / "app-data"))
    container = ServiceContainer(config)
    state = tmp_path / "active_vault.json"
    state.write_text(json.dumps({"active_vault_path": str(root)}), encoding="utf-8")
    monkeypatch.setattr(cli_main, "_state_file", lambda: state)
    monkeypatch.setattr(cli_main, "_container", container)
    return root, source, container


def test_cli_query_search_and_offline_ask(tmp_path, monkeypatch):
    _root, _source, _container = setup_cli(tmp_path, monkeypatch)
    result = runner.invoke(cli_main.app, ["query", 'content:"vector database"'])
    assert result.exit_code == 0, result.output
    assert "notes.txt" in result.output
    assert "ID" in result.output

    result = runner.invoke(cli_main.app, ["search", "retrieval"])
    assert result.exit_code == 0, result.output
    assert "notes.txt" in result.output

    result = runner.invoke(cli_main.app, ["ask", "Where is retrieval discussed?"])
    assert result.exit_code == 0, result.output
    assert "Retrieved evidence" in result.output
    assert "notes.txt" in result.output


def test_cli_malformed_rule_reports_caret_and_nonzero_status(tmp_path, monkeypatch):
    setup_cli(tmp_path, monkeypatch)
    result = runner.invoke(cli_main.app, ["query", "type:pdf AND ("])
    assert result.exit_code == 2
    assert "^" in result.output
    assert "column" in result.output.lower()


def test_cli_move_is_dry_run_and_apply_requires_saved_plan_id(tmp_path, monkeypatch):
    root, source, _container = setup_cli(tmp_path, monkeypatch)
    result = runner.invoke(cli_main.app, ["move", "--where", "content:retrieval", "--into", "Filed"])
    assert result.exit_code == 0, result.output
    assert "Dry run complete" in result.output
    assert source.exists()
    assert not (root / "Filed").exists()
    plan_id = re.search(r"Plan ID: ([0-9a-f-]+)", result.output).group(1)

    result = runner.invoke(cli_main.app, ["apply", plan_id, "--yes"])
    assert result.exit_code == 0, result.output
    assert "Committed" in result.output
    assert not source.exists()
    assert (root / "Filed" / "notes.txt").read_text(encoding="utf-8") == "Vector database retrieval evidence."


def test_cli_tags_and_rule_search_do_not_change_file_bytes(tmp_path, monkeypatch):
    root, source, _container = setup_cli(tmp_path, monkeypatch)
    original = source.read_bytes()
    result = runner.invoke(cli_main.app, ["tag", "add", "notes.txt", "Course Work"])
    assert result.exit_code == 0, result.output
    assert source.read_bytes() == original
    result = runner.invoke(cli_main.app, ["search", "--where", 'tag:"course work"'])
    assert result.exit_code == 0, result.output
    assert "notes.txt" in result.output
    result = runner.invoke(cli_main.app, ["tag", "remove", "notes.txt", "Course Work"])
    assert result.exit_code == 0, result.output
    assert (root / "notes.txt").read_bytes() == original


def test_cli_help_states_default_retrieval_and_explicit_commit():
    result = runner.invoke(cli_main.app, ["--help"])
    assert result.exit_code == 0
    assert "apply" in result.output
    assert "route" in result.output
    ask_help = runner.invoke(cli_main.app, ["ask", "--help"])
    assert "--synthesize" in ask_help.output
