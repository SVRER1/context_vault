from pathlib import Path
from typing import List, Dict, Set
from datetime import datetime
from contextvault.core.models import FileRecord, OrganisationPlan, PlannedOperation
from contextvault.core.vault import Vault

class DeterministicOrganiser:
    """Organises files based on deterministic attributes like extension, family, date, and size."""
    
    @staticmethod
    def organise_by_extension(files: List[FileRecord], vault: Vault) -> OrganisationPlan:
        plan = OrganisationPlan(directories_to_create=[], operations=[], untouched_files=[])
        dirs_to_create: Set[str] = set()
        
        ext_map = {
            '.pdf': 'PDF',
            '.docx': 'DOCX', '.doc': 'DOCX',
            '.pptx': 'PPTX',
            '.xlsx': 'Spreadsheets', '.csv': 'Spreadsheets',
            '.py': 'Code', '.java': 'Code', '.c': 'Code', '.cpp': 'Code', '.js': 'Code', '.ts': 'Code',
            '.html': 'Code', '.css': 'Code', '.sql': 'Code', '.sh': 'Code', '.ps1': 'Code',
            '.jpg': 'Images', '.png': 'Images', '.gif': 'Images', '.bmp': 'Images', '.svg': 'Images',
            '.zip': 'Archives', '.rar': 'Archives', '.7z': 'Archives', '.tar': 'Archives', '.gz': 'Archives',
            '.txt': 'Notes', '.md': 'Notes', '.rst': 'Notes', '.log': 'Notes'
        }
        
        for file in files:
            source_abs = vault.root_path / file.relative_path
            if not source_abs.exists():
                plan.untouched_files.append(file.relative_path)
                continue
                
            ext = file.extension.lower()
            folder_name = ext_map.get(ext, 'Other')
            rel_target = f"{folder_name}/{file.filename}"
            target_abs = vault.root_path / rel_target
            
                                    
            if source_abs.resolve() == target_abs.resolve():
                plan.untouched_files.append(file.relative_path)
                continue
                
                                                    
            if target_abs.exists():
                plan.untouched_files.append(file.relative_path)
                plan.warnings.append(f"Destination already exists: {rel_target}. Skipped to avoid collision.")
                continue
                
            dirs_to_create.add(folder_name)
            plan.operations.append(PlannedOperation(
                type="move",
                source=file.relative_path,
                destination=rel_target,
                reason=f"Organising by file extension: {folder_name}",
                confidence=1.0
            ))
            
        plan.directories_to_create = sorted(list(dirs_to_create))
        return plan

    @staticmethod
    def organise_by_family(files: List[FileRecord], vault: Vault) -> OrganisationPlan:
        plan = OrganisationPlan(directories_to_create=[], operations=[], untouched_files=[])
        dirs_to_create: Set[str] = set()
        
        family_map = {
            'document': 'Documents',
            'code': 'Code',
            'data': 'Data',
            'image': 'Images',
            'archive': 'Archives',
            'other': 'Other'
        }
        
        for file in files:
            source_abs = vault.root_path / file.relative_path
            if not source_abs.exists():
                plan.untouched_files.append(file.relative_path)
                continue
                
            folder_name = family_map.get(file.mime_family.lower(), 'Other')
            rel_target = f"{folder_name}/{file.filename}"
            target_abs = vault.root_path / rel_target
            
            if source_abs.resolve() == target_abs.resolve():
                plan.untouched_files.append(file.relative_path)
                continue
                
            if target_abs.exists():
                plan.untouched_files.append(file.relative_path)
                plan.warnings.append(f"Destination already exists: {rel_target}. Skipped to avoid collision.")
                continue
                
            dirs_to_create.add(folder_name)
            plan.operations.append(PlannedOperation(
                type="move",
                source=file.relative_path,
                destination=rel_target,
                reason=f"Organising by file family: {folder_name}",
                confidence=1.0
            ))
            
        plan.directories_to_create = sorted(list(dirs_to_create))
        return plan

    @staticmethod
    def organise_by_date(files: List[FileRecord], vault: Vault, mode: str = 'year-month') -> OrganisationPlan:
        plan = OrganisationPlan(directories_to_create=[], operations=[], untouched_files=[])
        dirs_to_create: Set[str] = set()
        
        for file in files:
            source_abs = vault.root_path / file.relative_path
            if not source_abs.exists():
                plan.untouched_files.append(file.relative_path)
                continue
            
            dt = datetime.fromtimestamp(file.mtime)
            
            if mode == 'year':
                folder_name = str(dt.year)
            else:
                folder_name = f"{dt.year}/{dt.strftime('%B')}"
                dirs_to_create.add(str(dt.year))
                
            rel_target = f"{folder_name}/{file.filename}"
            target_abs = vault.root_path / rel_target
            
            if source_abs.resolve() == target_abs.resolve():
                plan.untouched_files.append(file.relative_path)
                continue
                
            if target_abs.exists():
                plan.untouched_files.append(file.relative_path)
                plan.warnings.append(f"Destination already exists: {rel_target}. Skipped to avoid collision.")
                continue
                
            dirs_to_create.add(folder_name)
            plan.operations.append(PlannedOperation(
                type="move",
                source=file.relative_path,
                destination=rel_target,
                reason=f"Organising by date: {folder_name}",
                confidence=1.0
            ))
            
        plan.directories_to_create = sorted(list(dirs_to_create))
        return plan

    @staticmethod
    def organise_by_size(files: List[FileRecord], vault: Vault) -> OrganisationPlan:
        plan = OrganisationPlan(directories_to_create=[], operations=[], untouched_files=[])
        dirs_to_create: Set[str] = set()
        
        for file in files:
            source_abs = vault.root_path / file.relative_path
            if not source_abs.exists():
                plan.untouched_files.append(file.relative_path)
                continue
            
            size = file.size
            if size < 10240:
                folder_name = 'Tiny (<10KB)'
            elif size < 102400:
                folder_name = 'Small (10-100KB)'
            elif size < 1048576:
                folder_name = 'Medium (100KB-1MB)'
            elif size < 10485760:
                folder_name = 'Large (1-10MB)'
            else:
                folder_name = 'Very Large (>10MB)'
                
            rel_target = f"{folder_name}/{file.filename}"
            target_abs = vault.root_path / rel_target
            
            if source_abs.resolve() == target_abs.resolve():
                plan.untouched_files.append(file.relative_path)
                continue
                
            if target_abs.exists():
                plan.untouched_files.append(file.relative_path)
                plan.warnings.append(f"Destination already exists: {rel_target}. Skipped to avoid collision.")
                continue
                
            dirs_to_create.add(folder_name)
            plan.operations.append(PlannedOperation(
                type="move",
                source=file.relative_path,
                destination=rel_target,
                reason=f"Organising by size: {folder_name}",
                confidence=1.0
            ))
            
        plan.directories_to_create = sorted(list(dirs_to_create))
        return plan
