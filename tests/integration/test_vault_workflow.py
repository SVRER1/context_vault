import pytest
from datetime import datetime
from pathlib import Path

from contextvault.core.vault import Vault
from contextvault.core.models import VaultInfo
from contextvault.storage.database import Database
from contextvault.indexing.scanner import FileScanner
from contextvault.indexing.fingerprint import compute_sha256
from contextvault.organisation.rules import OrganisationRules
from contextvault.organisation.planner import OrganisationPlanner
from contextvault.organisation.executor import OrganisationExecutor
from contextvault.generation.generator import ContentGenerator
from contextvault.filesystem.undo import UndoManager
from contextvault.filesystem.operations import FileOperations

def test_full_vault_lifecycle_organise_and_undo(tmp_path):
                          
    vault_dir = tmp_path / "messy_vault"
    vault_dir.mkdir()
    
    file_data = {
        "os_lecture.txt": "CPU scheduling algorithms: FCFS, Round Robin, Priority Scheduling.",
        "java_lab.py": "public class Main { public static void main(String[] args) {} }",
        "assignment.txt": "Operating systems assignment on deadlocks and Banker algorithm.",
        "budget.csv": "Category,Amount\nBooks,120\nTuition,5000",
    }
    
    original_hashes = {}
    for filename, content in file_data.items():
        p = vault_dir / filename
        p.write_text(content, encoding="utf-8")
        original_hashes[filename] = compute_sha256(p)

    db_path = tmp_path / "index.db"
    db = Database(db_path)
    db.initialize()
    
    vault_info = VaultInfo(
        id="integration-vault",
        display_name="Messy Vault",
        absolute_path=str(vault_dir),
        created_at=datetime.now(),
        last_opened_at=datetime.now()
    )
    db.execute(
        """INSERT INTO vaults 
           (id, display_name, absolute_path, created_at, last_opened_at, file_count, chunk_count, index_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (vault_info.id, vault_info.display_name, vault_info.absolute_path, vault_info.created_at.isoformat(), vault_info.last_opened_at.isoformat(), 0, 0, 1)
    )
    db.conn.commit()
    vault = Vault(vault_info)
    
                   
    scanner = FileScanner(vault, db)
    files = scanner.scan()
    assert len(files) == 4
    
                                                              
    planner = OrganisationPlanner()
    rules = OrganisationRules(strategy="deterministic", primary_grouping="file-type")
    plan = planner.create_plan(files, vault, rules)
    assert len(plan.operations) == 4
    
                                  
    file_ops = FileOperations(db)
    executor = OrganisationExecutor(vault, db, file_ops)
    records = executor.execute(plan, approved=True)
    assert len(records) == 4 + len(plan.directories_to_create)                            
    
                                                                      
    for filename in file_data.keys():
                                          
        moved_op = next(op for op in plan.operations if op.source == filename)
        new_loc = vault.root_path / moved_op.destination
        assert new_loc.exists()
        current_hash = compute_sha256(new_loc)
        assert current_hash == original_hashes[filename], f"Hash altered for {filename}!"

                                         
    generator = ContentGenerator(llm_client=None, retriever=None, vault=vault, db=db)
    asset = generator.generate(asset_type="summary", topic="Operating Systems")
    assert Path(vault.root_path / asset.relative_path).exists()
    assert "Operating Systems" in (vault.root_path / asset.relative_path).read_text(encoding="utf-8")
    
                                            
    for filename in file_data.keys():
        moved_op = next(op for op in plan.operations if op.source == filename)
        new_loc = vault.root_path / moved_op.destination
        assert compute_sha256(new_loc) == original_hashes[filename]

                          
    undo_mgr = UndoManager(db, vault)
    batch_id = records[0].batch_id
    undo_records = undo_mgr.undo_batch(batch_id)
    assert len(undo_records) >= 4
    
                                                                                    
    for filename in file_data.keys():
        orig_file = vault_dir / filename
        assert orig_file.exists(), f"File {filename} was not restored!"
        assert compute_sha256(orig_file) == original_hashes[filename], f"Hash mismatch on restored file {filename}!"
