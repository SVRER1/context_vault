from typing import List
from pathlib import Path
from contextvault.core.models import FileRecord, OrganisationPlan, PlannedOperation
from contextvault.core.vault import Vault
from contextvault.organisation.rules import OrganisationRules
from contextvault.organisation.deterministic import DeterministicOrganiser
from contextvault.organisation.semantic import SemanticOrganiser

class HybridOrganiser:
    def __init__(self, deterministic: DeterministicOrganiser, semantic: SemanticOrganiser):
        self.deterministic = deterministic
        self.semantic = semantic

    def organise(self, files: List[FileRecord], vault: Vault, rules: OrganisationRules) -> OrganisationPlan:
                                                         
        semantic_plan = self.semantic.organise(files, vault, rules)
        
                                                                                  
        secondary_mode = rules.secondary_grouping or "file-type"
        dirs_to_create = set(semantic_plan.directories_to_create)
        new_operations: List[PlannedOperation] = []

        ext_to_folder = {
            ".pdf": "PDF", ".docx": "DOCX", ".doc": "DOCX", ".pptx": "PPTX",
            ".xlsx": "Data", ".csv": "Data", ".py": "Code", ".java": "Code",
            ".c": "Code", ".cpp": "Code", ".js": "Code", ".ts": "Code",
            ".txt": "Notes", ".md": "Notes", ".rst": "Notes",
        }

        for op in semantic_plan.operations:
            src_path = Path(op.source)
            ext = src_path.suffix.lower()
            sub_folder = ext_to_folder.get(ext, ext.replace(".", "").upper() or "Other")
            
                                                                  
            current_dest = Path(op.destination) if op.destination else Path(op.source)
            primary_cat = current_dest.parent.name or "General"
            
            hybrid_dest_dir = f"{primary_cat}/{sub_folder}"
            hybrid_dest = f"{hybrid_dest_dir}/{src_path.name}"
            
                             
            target_abs = vault.root_path / hybrid_dest
            if target_abs.exists():
                semantic_plan.warnings.append(f"Destination exists: {hybrid_dest}. Kept in {op.destination}")
                new_operations.append(op)
                continue

            dirs_to_create.add(hybrid_dest_dir)
            new_operations.append(PlannedOperation(
                type="move",
                source=op.source,
                destination=hybrid_dest,
                reason=f"{op.reason} -> {sub_folder}",
                confidence=op.confidence
            ))

        semantic_plan.operations = new_operations
        semantic_plan.directories_to_create = sorted(list(dirs_to_create))
        return semantic_plan
