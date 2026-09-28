import pytest
from unittest.mock import MagicMock
from pathlib import Path
from datetime import datetime

from contextvault.agent.orchestrator import Orchestrator
from contextvault.core.vault import Vault
from contextvault.core.models import VaultInfo, SearchResult, Citation, RAGResponse, GeneratedAsset, OrganisationPlan, PlannedOperation
from contextvault.duplicates.models import DuplicateGroup

@pytest.fixture
def mock_vault(tmp_path):
    info = VaultInfo(
        id="test-vault-id",
        display_name="TestVault",
        absolute_path=str(tmp_path),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
        file_count=5,
        chunk_count=10,
        index_version=1
    )
    return Vault(info)

def test_orchestrator_handles_search_with_real_results(mock_vault):
    mock_rag = MagicMock()
    mock_rag.search.return_value = [
        SearchResult(
            file_id="1",
            relative_path="docs/lecture1.txt",
            filename="lecture1.txt",
            snippet="Introduction to operating system scheduling algorithms.",
            score=0.88,
            page=1
        )
    ]
    
    orch = Orchestrator(services={"rag_service": mock_rag})
    result = orch.handle_query("search for scheduling algorithms", mock_vault)
    
    assert result.result_type == "search_results"
    assert "lecture1.txt" in result.content
    assert "0.88" in result.content
    assert len(result.data["results"]) == 1
    assert "RAG response for:" not in result.content

def test_orchestrator_handles_duplicates(mock_vault):
    mock_org = MagicMock()
    mock_org.detect_duplicates.return_value = (
        [DuplicateGroup(group_type="exact", hash="abc123456789", files=[], confidence=1.0, reason="exact")],
        []
    )
    
    orch = Orchestrator(services={"organisation_service": mock_org})
    result = orch.handle_query("check for duplicates", mock_vault)
    
    assert result.result_type == "duplicates"
    assert "Duplicate & Revision Analysis" in result.content
    assert "abc123456789" in result.content
    assert "Duplicate analysis complete." != result.content

def test_orchestrator_handles_generation(mock_vault, tmp_path):
    mock_gen = MagicMock()
    gen_file = tmp_path / "Generated" / "Study_Guide.md"
    gen_file.parent.mkdir(parents=True, exist_ok=True)
    gen_file.write_text("# Study Guide: Memory\n\nVirtual memory notes.", encoding="utf-8")
    
    mock_gen.generate.return_value = GeneratedAsset(
        id="gen-1",
        vault_id="test-vault-id",
        asset_type="study-guide",
        title="Study Guide - Memory",
        filename="Study_Guide.md",
        relative_path="Generated/Study_Guide.md",
        created_at=datetime.now()
    )
    
    orch = Orchestrator(services={"generation_service": mock_gen})
    result = orch.handle_query("generate a study guide on memory", mock_vault)
    
    assert result.result_type == "generated_file"
    assert "Generated: Study Guide - Memory" in result.content
    assert "Virtual memory notes" in result.content
    assert "Content generated." != result.content

def test_orchestrator_reports_actual_capabilities(mock_vault):
    orch = Orchestrator(services={"vault": mock_vault})
    result = orch.handle_query("what can you do", mock_vault)

    assert result.result_type == "capabilities"
    assert "ocr_image" in result.content
    assert "does not autonomously browse the web" in result.content

def test_orchestrator_handles_status(mock_vault):
    mock_vs = MagicMock()
    mock_vs.get_vault_status.return_value = {
        "file_count": 12,
        "chunk_count": 45,
        "last_indexed_at": "2026-09-03"
    }
    
    orch = Orchestrator(services={"vault_service": mock_vs})
    result = orch.handle_query("status of my vault", mock_vault)
    
    assert result.result_type == "status"
    assert "Vault Status: `TestVault`" in result.content
    assert "gemma4:e2b" in result.content
    assert "12" in result.content
