import pytest
from pathlib import Path
from datetime import datetime

from contextvault.tools.peeker import ShallowPeeker
from contextvault.core.vault import Vault
from contextvault.core.models import VaultInfo

@pytest.fixture
def sample_vault(tmp_path):
                                       
    long_file = tmp_path / "long_notes.txt"
    long_file.write_text("\n".join(f"Line {i}: Some content here" for i in range(1, 100)), encoding="utf-8")

    csv_file = tmp_path / "sales.csv"
    csv_file.write_text("Month,Revenue,Units\nJan,100,10\nFeb,150,15\nMar,200,20\n", encoding="utf-8")

    info = VaultInfo(
        id="peek-test-vault",
        display_name="PeekVault",
        absolute_path=str(tmp_path),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
        file_count=2,
        chunk_count=0,
        index_version=1,
    )
    return Vault(info)

def test_peek_file_enforces_line_clamp(sample_vault):
    long_file = sample_vault.root_path / "long_notes.txt"
    
                                           
    peek_res = ShallowPeeker.peek_file(long_file, max_lines=50)
    assert peek_res["line_count"] == 20
    assert "Line 20" in peek_res["preview"]
    assert "Line 21" not in peek_res["preview"]

                                          
    peek_min = ShallowPeeker.peek_file(long_file, max_lines=3)
    assert peek_min["line_count"] == 10

def test_peek_csv_extracts_columns(sample_vault):
    csv_file = sample_vault.root_path / "sales.csv"
    peek_res = ShallowPeeker.peek_file(csv_file, max_lines=15)
    
    assert peek_res["columns"] == ["Month", "Revenue", "Units"]
    assert "Jan" in peek_res["preview"]
    assert peek_res["mime_family"] == "data"

def test_inspect_directory_generates_digest(sample_vault):
    profiles = ShallowPeeker.inspect_directory(sample_vault, max_lines_per_file=15)
    assert len(profiles) == 2
    
    digest = ShallowPeeker.generate_directory_digest(profiles)
    assert "Vault Directory Digest" in digest
    assert "long_notes.txt" in digest
    assert "sales.csv" in digest
