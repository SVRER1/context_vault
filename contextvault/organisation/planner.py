from typing import List, Optional, Any
from contextvault.core.models import FileRecord, OrganisationPlan
from contextvault.core.vault import Vault
from contextvault.core.exceptions import OrganisationError
from contextvault.llm.client import LLMClient
from contextvault.storage.database import Database
from contextvault.organisation.rules import OrganisationRules
from contextvault.organisation.deterministic import DeterministicOrganiser
from contextvault.organisation.semantic import SemanticOrganiser
from contextvault.organisation.hybrid import HybridOrganiser


class OrganisationPlanner:
    def create_plan(
        self,
        files: List[FileRecord],
        vault: Vault,
        rules: OrganisationRules,
        llm_client: Optional[LLMClient] = None,
        db: Optional[Database] = None, 
        retriever: Optional[Any] = None
    ) -> OrganisationPlan:
        
                                                        
        if not files:
            from contextvault.indexing.scanner import FileScanner
            scanner = FileScanner(vault, db) if db else None
            if scanner:
                files = scanner.scan()

        if rules.strategy == 'deterministic':
            if rules.primary_grouping == 'file-type':
                return DeterministicOrganiser.organise_by_extension(files, vault)
            elif rules.primary_grouping == 'file-family':
                return DeterministicOrganiser.organise_by_family(files, vault)
            elif rules.primary_grouping in ('date-year', 'date-month'):
                mode = 'year' if rules.primary_grouping == 'date-year' else 'year-month'
                return DeterministicOrganiser.organise_by_date(files, vault, mode=mode)
            elif rules.primary_grouping == 'size':
                return DeterministicOrganiser.organise_by_size(files, vault)
            else:
                return DeterministicOrganiser.organise_by_extension(files, vault)
                
        elif rules.strategy in ('semantic', 'custom'):
            semantic = SemanticOrganiser(llm_client, db, retriever)
            return semantic.organise(files, vault, rules)
            
        elif rules.strategy == 'hybrid':
            deterministic = DeterministicOrganiser()
            semantic = SemanticOrganiser(llm_client, db, retriever)
            hybrid = HybridOrganiser(deterministic, semantic)
            return hybrid.organise(files, vault, rules)
            
                                             
        return DeterministicOrganiser.organise_by_extension(files, vault)
