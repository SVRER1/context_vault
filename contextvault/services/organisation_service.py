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
from contextvault.organisation.executor import OrganisationExecutor
from contextvault.filesystem.operations import FileOperations
from contextvault.storage.database import Database

logger = logging.getLogger(__name__)


class OrganisationService:
    """Service for organizing and restructuring vault files."""

    def __init__(self, vault: Vault, db: Database, llm_client: Any, retriever: Any):
        self.vault = vault
        self.db = db
        self.llm_client = llm_client
        self.retriever = retriever

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
        scope = self.vault.scope_relative_path(subfolder)
        files = self._get_files(scope)
        if not files:
            return OrganisationPlan(
                directories_to_create=[],
                operations=[],
                warnings=["No files found in vault."],
                untouched_files=[],
                source_scope=scope,
            )

        planner = OrganisationPlanner()
        plan = planner.create_plan(
            files=files,
            vault=self.vault,
            rules=rules,
            llm_client=self.llm_client,
            db=self.db,
            retriever=self.retriever,
        )
        plan.source_scope = scope

                                                                             
                                                                              
                                                                 
        if scope:
            scoped_dirs = []
            for directory in plan.directories_to_create:
                scoped_dirs.append(f"{scope}/{directory}")
            plan.directories_to_create = sorted(set(scoped_dirs))

            scoped_ops = []
            seen_destinations = set()
            for operation in plan.operations:
                destination = f"{scope}/{operation.destination}"
                target = self.vault.root_path / destination
                source = self.vault.root_path / operation.source
                if destination in seen_destinations or (target.exists() and target.resolve() != source.resolve()):
                    plan.untouched_files.append(operation.source)
                    plan.warnings.append(f"Destination already exists or is duplicated: {destination}. Skipped.")
                    continue
                seen_destinations.add(destination)
                operation.destination = destination
                scoped_ops.append(operation)
            plan.operations = scoped_ops
        return plan

    def apply(self, plan: OrganisationPlan) -> list[OperationRecord]:
        """Apply an approved organisation plan.

        Args:
            plan: The approved organisation plan.

        Returns:
            List of completed OperationRecords.
        """
        if plan.source_scope:
            scope = self.vault.scope_root(plan.source_scope)
            for operation in plan.operations:
                if not self.vault.is_in_scope(operation.source, plan.source_scope) or not self.vault.is_in_scope(operation.destination or "", plan.source_scope):
                    raise ValueError("Organisation plan contains a path outside its selected source scope.")

        file_ops = FileOperations(self.db)
        executor = OrganisationExecutor(
            vault=self.vault,
            db=self.db,
            file_ops=file_ops,
        )
        records = executor.execute(plan, approved=True)

                                                       
        for record in records:
            if record.status == "completed" and record.operation_type == "move":
                self.db.execute(
                    "UPDATE files SET relative_path = ?, filename = ? WHERE relative_path = ? AND vault_id = ?",
                    (
                        record.destination_path,
                        record.destination_path.split("/")[-1] if "/" in record.destination_path else record.destination_path.split("\\\\")[-1],
                        record.source_path,
                        self.vault.vault_id,
                    ),
                )

        self.db.conn.commit()
        return records

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
