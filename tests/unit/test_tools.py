import pytest
from pathlib import Path
from datetime import datetime

from contextvault.tools.base import ToolRegistry, ToolResult
from contextvault.tools import build_default_tool_registry
from contextvault.core.vault import Vault
from contextvault.core.models import VaultInfo
from contextvault.core.config import AppConfig
from contextvault.retrieval.filesystem_service import FilesystemRetrievalService

@pytest.fixture
def test_vault(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("Line 1\nLine 2\nLine 3\n", encoding="utf-8")
    info = VaultInfo(
        id="tool-test-vault",
        display_name="ToolVault",
        absolute_path=str(tmp_path),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
        file_count=1,
        chunk_count=0,
        index_version=1,
    )
    return Vault(info)

def test_tool_registry_registration_and_execution(test_vault):
    reg = build_default_tool_registry(test_vault, services={})
    
    assert reg.get("peek_file") is not None
    assert reg.get("peek_directory") is not None
    assert reg.get("inspect_dataset") is not None
    assert reg.get("generate_chart") is not None
    assert reg.get("compile_pdf_artifact") is not None
    assert reg.get("ocr_image") is not None
    
    
    res = reg.execute("peek_file", {"file_path": "notes.txt", "max_lines": 15})
    assert res.success is True
    assert res.data["line_count"] == 3
    assert "Line 1" in res.data["preview"]

def test_tool_registry_prompt_generation(test_vault):
    reg = build_default_tool_registry(test_vault, services={})
    prompt = reg.get_tool_prompt()
    
    assert "peek_directory" in prompt
    assert "generate_chart" in prompt
    assert "compile_pdf_artifact" in prompt
    assert "ocr_image" in prompt


def test_tool_registry_exposes_scope_safe_filesystem_retrieval(test_vault, tmp_path):
    retrieval = FilesystemRetrievalService(
        test_vault,
        llm_client=None,
        config=AppConfig(app_data_dir=str(tmp_path / "app-data")),
    )
    reg = build_default_tool_registry(
        test_vault,
        {"filesystem_retrieval_service": retrieval},
    )

    assert reg.get("survey_scope") is not None
    assert reg.get("search_scope_text") is not None
    assert reg.get("build_evidence") is not None
    result = reg.execute("search_scope_text", {"query": "Line 2", "subfolder": ""})
    assert result.success is True
    assert result.data[0]["survey"]["relative_path"] == "notes.txt"
