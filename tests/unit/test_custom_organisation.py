import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock

from contextvault.core.vault import Vault
from contextvault.core.models import VaultInfo, FileRecord
from contextvault.organisation.rules import OrganisationRules
from contextvault.organisation.planner import OrganisationPlanner
from contextvault.organisation.semantic import SemanticOrganiser

@pytest.fixture
def custom_vault(tmp_path):
    
    (tmp_path / "calculus_hw.txt").write_text("Calculus derivatives and integrals\n", encoding="utf-8")
    (tmp_path / "algorithm_lab.py").write_text("def quicksort(arr): return arr\n", encoding="utf-8")
    (tmp_path / "quantum_mechanics.pdf").write_text("Schrodinger wave equation\n", encoding="utf-8")

    info = VaultInfo(
        id="custom-org-vault",
        display_name="CustomOrgVault",
        absolute_path=str(tmp_path),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
        file_count=3,
        chunk_count=0,
        index_version=1,
    )
    return Vault(info)

def test_custom_parameter_division_creates_target_directories(custom_vault):
    files = [
        FileRecord(
            id="f1", vault_id="custom-org-vault", relative_path="calculus_hw.txt",
            filename="calculus_hw.txt", extension=".txt", size=50, mtime=0, created_time=0,
            sha256="h1", mime_family="text", parser="PlainTextParser"
        ),
        FileRecord(
            id="f2", vault_id="custom-org-vault", relative_path="algorithm_lab.py",
            filename="algorithm_lab.py", extension=".py", size=50, mtime=0, created_time=0,
            sha256="h2", mime_family="code", parser="PlainTextParser"
        ),
    ]

    rules = OrganisationRules(
        strategy="semantic",
        primary_grouping="custom",
        custom_parameter="Divide by course: Math, Computer Science, Physics",
    )

    planner = OrganisationPlanner()
    plan = planner.create_plan(files=files, vault=custom_vault, rules=rules)

    
    assert len(plan.directories_to_create) > 0
    assert len(plan.operations) > 0

    
    destinations = [op.destination for op in plan.operations]
    assert any("/calculus_hw.txt" in d for d in destinations)
    assert any("/algorithm_lab.py" in d for d in destinations)
