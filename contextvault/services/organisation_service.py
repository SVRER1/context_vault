"""Organisation service for vault restructuring.

Orchestrates deterministic, semantic, and hybrid file organisation.
Handles duplicate detection and organisation plan execution.
"""

import logging
from typing import Any

from contextvault.core.models import FileRecord, OperationRecord, OrganisationPlan
from contextvault.core.vault import Vault
from contextvault.duplicates.exact import ExactDuplicateDetector
from contextvault.duplicates.versions import VersionDetector
from contextvault.duplicates.models import DuplicateGroup
from contextvault.organisation.planner import OrganisationPlanner
from contextvault.organisation.rules import OrganisationRules
from contextvault.storage.database import Database

logger = logging.getLogger(__name__)


class OrganisationService:
    """Service for organizing and restructuring vault files."""

    def __init__(self, vault: Vault, db: Database, llm_client: Any = None, retriever: Any = None,
                 plan_service: Any = None, execution_service: Any = None):
        self.vault = vault
        self.db = db
        self.llm_client = llm_client
        self.retriever = retriever
        self._plan_service = plan_service
        self._execution_service = execution_service

    def _get_files(self, subfolder: str | None = None) -> list[FileRecord]:
        """Get all files from the vault database, auto-scanning if empty."""
        rows = self.db.fetch_all(
            "SELECT * FROM files WHERE vault_id = ?",
            (self.vault.vault_id,),
        )
        if not rows:
            from contextvault.indexing.scanner import FileScanner
            logger.info(f"No files in database for vault {self.vault.display_name}. Running on-the-fly scan...")
            files = FileScanner(self.vault, self.db).scan()
        else:
            files = []
            for row in rows:
                try:
                    files.append(FileRecord(
                        id=row["id"],
                        vault_id=row["vault_id"],
                        relative_path=row["relative_path"],
                        filename=row["filename"],
                        extension=row["extension"],
                        size=row["size"],
                        mtime=row["mtime"],
                        created_time=row.get("created_time", row["mtime"]),
                        sha256=row["sha256"],
                        mime_family=row["mime_family"],
                        parser=row.get("parser"),
                        parse_status=row.get("parse_status", "pending"),
                    ))
                except Exception as e:
                    logger.warning(f"Could not load file record: {e}")

        if subfolder:
            self.vault.scope_root(subfolder)                                          
            files = [f for f in files if self.vault.is_in_scope(f.relative_path, subfolder)]
        return files

    def preview(self, rules: OrganisationRules, subfolder: str | None = None) -> OrganisationPlan:
        """Generate an organisation plan preview.

        Args:
            rules: Organisation configuration (strategy, grouping, etc.)

        Returns:
            OrganisationPlan ready for user review.
        """
        return self.preview_plan(rules, subfolder).to_organisation_plan()

    def preview_plan(self, rules: OrganisationRules, subfolder: str | None = None):
        """Return the shared immutable, persisted plan used by every interface."""
        scope = self.vault.scope_relative_path(subfolder)
        plan_service = self._plan_service
        if plan_service is None:
            from contextvault.filesystem.plan_service import PlanService
            plan_service = PlanService(self.vault, self.db)
        return plan_service.preview_strategy(rules, scope=scope)

    def commit_plan(self, plan_id: str, digest: str, *, approved: bool):
        """Execute a reviewed persisted plan through the durable journal."""
        executor = self._execution_service
        if executor is None:
            from contextvault.filesystem.execution_service import ExecutionService
            executor = ExecutionService(self.vault, self.db, self._plan_service)
        return executor.commit(plan_id, digest, approved=approved)

    def apply(self, plan: OrganisationPlan) -> list[OperationRecord]:
        """Reject direct mutation of legacy previews without a persisted digest."""
        raise ValueError(
            "Legacy OrganisationPlan objects cannot be executed safely. Create a shared "
            "preview_plan, review its mapping, then call commit_plan(plan_id, digest, approved=True)."
        )

    def detect_duplicates(self, subfolder: str | None = None) -> tuple[list[DuplicateGroup], list[DuplicateGroup]]:
        """Detect exact duplicates and possible file versions.

        Returns:
            Tuple of (exact_duplicates, possible_versions).
        """
        files = self._get_files(subfolder)

        exact_detector = ExactDuplicateDetector()
        exact_groups = exact_detector.detect(files)

        version_detector = VersionDetector()
        version_groups = version_detector.detect(files)

        return exact_groups, version_groups
