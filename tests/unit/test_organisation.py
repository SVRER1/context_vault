from datetime import datetime
from contextvault.core.vault import Vault
from contextvault.core.models import VaultInfo, FileRecord
from contextvault.organisation.rules import OrganisationRules
from contextvault.organisation.planner import OrganisationPlanner
from contextvault.organisation.deterministic import DeterministicOrganiser

def test_deterministic_by_extension(tmp_path):
    vault_dir = tmp_path / "v"
    vault_dir.mkdir()
    
                         
    (vault_dir / "doc.pdf").touch()
    (vault_dir / "notes.txt").touch()
    (vault_dir / "script.py").touch()
    
    vault = Vault(VaultInfo(
        id="v1", display_name="V", absolute_path=str(vault_dir),
        created_at=datetime.now(), last_opened_at=datetime.now()
    ))
    
    files = [
        FileRecord(id="1", vault_id="v1", relative_path="doc.pdf", filename="doc.pdf", extension=".pdf", size=10, mtime=1.0, created_time=1.0, sha256="h1", mime_family="document"),
        FileRecord(id="2", vault_id="v1", relative_path="notes.txt", filename="notes.txt", extension=".txt", size=10, mtime=1.0, created_time=1.0, sha256="h2", mime_family="document"),
        FileRecord(id="3", vault_id="v1", relative_path="script.py", filename="script.py", extension=".py", size=10, mtime=1.0, created_time=1.0, sha256="h3", mime_family="code"),
    ]
    
    plan = DeterministicOrganiser.organise_by_extension(files, vault)
    assert len(plan.operations) == 3
    destinations = [op.destination for op in plan.operations]
    assert "PDF/doc.pdf" in destinations
    assert "Notes/notes.txt" in destinations
    assert "Code/script.py" in destinations
    assert "PDF" in plan.directories_to_create
    assert "Notes" in plan.directories_to_create
    assert "Code" in plan.directories_to_create

def test_organisation_planner_deterministic(tmp_path):
    vault_dir = tmp_path / "v"
    vault_dir.mkdir()
    (vault_dir / "image.png").touch()
    
    vault = Vault(VaultInfo(
        id="v1", display_name="V", absolute_path=str(vault_dir),
        created_at=datetime.now(), last_opened_at=datetime.now()
    ))
    files = [
        FileRecord(id="1", vault_id="v1", relative_path="image.png", filename="image.png", extension=".png", size=100, mtime=1.0, created_time=1.0, sha256="h1", mime_family="image")
    ]
    
    planner = OrganisationPlanner()
    rules = OrganisationRules(strategy="deterministic", primary_grouping="file-family")
    plan = planner.create_plan(files, vault, rules)
    assert len(plan.operations) == 1
    assert plan.operations[0].destination == "Images/image.png"
