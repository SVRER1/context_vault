"""Preview, validate, persist, and reconstruct deterministic file-operation plans."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from contextvault.core.config import AppConfig, get_config
from contextvault.core.vault import Vault
from contextvault.filesystem.plan_models import (
    DestinationFingerprint,
    FileFingerprint,
    FileOperationPlan,
    PlanIssue,
    PlannedFileOperation,
    RouteEntry,
    RouteSpec,
    route_to_data,
)
from contextvault.indexing.fingerprint import compute_sha256
from contextvault.query.ast import RuleNode, serialize
from contextvault.query.executor import RuleExecutor
from contextvault.query.validation import validate
from contextvault.retrieval.filesystem_policy import validate_source_scope
from contextvault.storage.database import Database
from contextvault.storage.index_repository import IndexRepository

_EXTENSION_FOLDERS = {
    ".pdf": "PDF", ".docx": "DOCX", ".doc": "DOCX", ".pptx": "PPTX",
    ".xlsx": "Spreadsheets", ".csv": "Spreadsheets",
    ".py": "Code", ".java": "Code", ".c": "Code", ".cpp": "Code",
    ".js": "Code", ".ts": "Code", ".html": "Code", ".css": "Code",
    ".sql": "Code", ".sh": "Code", ".ps1": "Code",
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images",
    ".bmp": "Images", ".svg": "Images",
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives", ".tar": "Archives", ".gz": "Archives",
    ".txt": "Notes", ".md": "Notes", ".rst": "Notes", ".log": "Notes",
}
_FAMILY_FOLDERS = {
    "document": "Documents", "code": "Code", "data": "Data",
    "image": "Images", "archive": "Archives", "other": "Other",
}
_GROUP_KEYS = {"extension", "family", "year", "year-month", "size", "first-tag", "hash-prefix"}
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class PlanService:
    """Create whole-batch validated previews without changing source files."""

    def __init__(self, vault: Vault, db: Database, config: AppConfig | None = None, *,
                 ttl_hours: int = 24, rule_executor: RuleExecutor | None = None):
        self.vault = vault
        self.db = db
        self.config = config or get_config()
        self.ttl = timedelta(hours=max(1, int(ttl_hours)))
        self.rule_executor = rule_executor or RuleExecutor(vault, db, self.config)
        self.repository = IndexRepository(db)

    def preview_rule(
        self,
        rule: RuleNode,
        destination_directory: str,
        *,
        scope: str | None = None,
        action: str = "move",
        group_by: str | None = None,
    ) -> FileOperationPlan:
        canonical_rule = validate(rule)
        route = RouteSpec(
            entries=(RouteEntry(canonical_rule, destination_directory, action),),
            fallback="keep",
            group_by=group_by,
        )
        return self.preview_route(route, scope=scope)

    def preview_route(self, route: RouteSpec, *, scope: str | None = None) -> FileOperationPlan:
        self._validate_route(route)
        validate_source_scope(self.vault, scope, self.config.generated_output_folder)
        snapshot = self.rule_executor.prepare_universe(scope=scope, reconcile=True)
        skips: list[PlanIssue] = []
        warnings: list[PlanIssue] = []
        assignments: dict[str, tuple[RouteEntry, str]] = {}
        unresolved: set[str] = set()

        for entry_index, entry in enumerate(route.entries):
            selection = self.rule_executor.evaluate_prepared(entry.rule, snapshot)
            for file_id in selection.unknown_ids:
                if file_id not in assignments:
                    unresolved.add(file_id)
            for file_id in selection.matched_ids:
                if file_id in unresolved or file_id in assignments:
                    continue
                reason = f"First matching route entry {entry_index + 1}"
                assignments[file_id] = (entry, reason)

        for file_id in sorted(unresolved, key=lambda value: (snapshot.rows_by_id[value]["path_key"], value)):
            row = snapshot.rows_by_id[file_id]
            skips.append(PlanIssue(
                "unknown_rule_result", "Rule result is incomplete; send this file for review.",
                file_id, row["relative_path"],
            ))

        for file_id, row in snapshot.rows_by_id.items():
            if file_id in assignments or file_id in unresolved:
                continue
            if route.fallback == "keep":
                skips.append(PlanIssue("fallback_keep", "No route matched; file remains in place.", file_id, row["relative_path"]))
            else:
                skips.append(PlanIssue("fallback_review", "No route matched; file requires review.", file_id, row["relative_path"]))

        proposed = []
        for file_id, (entry, reason) in assignments.items():
            row = snapshot.rows_by_id[file_id]
            destination_dir = self._join_scope(scope, entry.destination_directory)
            if route.group_by:
                category = self._group_value(route.group_by, row)
                destination_dir = f"{destination_dir}/{category}" if destination_dir else category
                if route.group_by == "first-tag":
                    warnings.append(PlanIssue(
                        "first_tag_grouping", "Multiple tags group by the lexicographically first normalized tag.", file_id, row["relative_path"]
                    ))
            proposed.append((file_id, row, destination_dir, entry.action, reason))

        route_data = route_to_data(route)
        route_data["resolved_scope"] = scope
        route_data["warnings"] = [_issue_payload(item) for item in warnings]
        return self._build_and_persist(
            snapshot, scope, {"kind": "route"}, route_data, proposed, skips, warnings
        )

    def preview_strategy(self, strategy: Any, *, scope: str | None = None) -> FileOperationPlan:
        """Adapt existing deterministic group choices to the shared plan contract."""
        validate_source_scope(self.vault, scope, self.config.generated_output_folder)
        snapshot = self.rule_executor.prepare_universe(scope=scope, reconcile=True)
        grouping = str(getattr(strategy, "primary_grouping", "file-type"))
        proposed = []
        skips: list[PlanIssue] = []
        warnings: list[PlanIssue] = []
        if getattr(strategy, "strategy", "deterministic") != "deterministic" or grouping not in {
            "file-type", "file-family", "date-year", "date-month", "size"
        }:
            for file_id, row in snapshot.rows_by_id.items():
                skips.append(PlanIssue(
                    "explicit_rule_route_required",
                    "Model-classified/custom destinations are disabled; create a deterministic RouteSpec.",
                    file_id,
                    row["relative_path"],
                ))
            warnings.append(PlanIssue(
                "model_free_routing", "Filesystem destinations require deterministic grouping rules.",
            ))
        else:
            for file_id, row in snapshot.rows_by_id.items():
                category = self._legacy_group(grouping, row)
                directory = f"{scope}/{category}" if scope else category
                proposed.append((file_id, row, directory, "move", f"Deterministic grouping: {grouping}"))
        route = {"kind": "legacy_strategy", "strategy": getattr(strategy, "strategy", "deterministic"), "grouping": grouping}
        return self._build_and_persist(snapshot, scope, route, route, proposed, skips, warnings)

    def preview_rename(self, relative_path: str, new_name: str, *, scope: str | None = None) -> FileOperationPlan:
        """Plan one basename rename, including case-only Windows renames."""
        validate_source_scope(self.vault, scope, self.config.generated_output_folder)
        snapshot = self.rule_executor.prepare_universe(scope=scope, reconcile=True)
        path_key = relative_path.replace("\\", "/").strip("/").casefold()
        row = next((value for value in snapshot.rows_by_id.values()
                    if value["path_key"] == path_key), None)
        if row is None:
            raise KeyError(f"File is not in the indexed scope: {relative_path}")
        if scope and not self.vault.is_in_scope(row["relative_path"], scope):
            raise ValueError("Rename source is outside the selected scope.")
        parent = row["relative_path"].rpartition("/")[0]
        updated = dict(row)
        updated["filename"] = str(new_name)
        proposed = [(row["id"], updated, parent, "rename", f"Rename to {new_name}")]
        selection = {"kind": "file_id", "file_id": row["id"]}
        route = {"kind": "rename", "new_name": str(new_name)}
        return self._build_and_persist(snapshot, scope, selection, route, proposed, [], [])

    def _build_and_persist(self, snapshot, scope, selection_data, route_data, proposed, skips, warnings):
        conflicts: list[PlanIssue] = []
        preliminary: list[dict] = []
        targets: dict[str, list[int]] = {}
        estimated_bytes = 0

        for file_id, row, destination_dir, action, reason in proposed:
            source_rel = row["relative_path"].replace("\\", "/")
            directory, validation_messages = self._clean_directory(destination_dir)
            for code, message in validation_messages:
                conflicts.append(PlanIssue(code, message, file_id, source_rel))
            filename = row["filename"]
            name_issues = self._clean_filename(filename)
            for code, message in name_issues:
                per_file_codes.append(code)
                conflicts.append(PlanIssue(code, message, file_id, filename))
            target_rel = f"{directory}/{filename}" if directory else filename
            target_rel = target_rel.replace("\\", "/")
            source_path = self.vault.root_path / source_rel
            destination_path = self.vault.root_path / target_rel
            per_file_codes = [code for code, _ in validation_messages]

            try:
                if not source_path.exists() or not source_path.is_file():
                    per_file_codes.append("source_missing")
                    conflicts.append(PlanIssue("source_missing", "Source is missing or is not a regular file.", file_id, source_rel))
                if source_path.is_symlink():
                    per_file_codes.append("source_symlink")
                    conflicts.append(PlanIssue("source_symlink", "Symlinked sources are not eligible for file operations.", file_id, source_rel))
                canonical_source = self.vault.validate_path(source_path)
                canonical_destination = self.vault.validate_path(destination_path)
                scope_root = self.vault.scope_root(scope)
                canonical_source.relative_to(scope_root)
                canonical_destination.relative_to(scope_root)
            except (OSError, ValueError, RuntimeError) as exc:
                per_file_codes.append("scope_or_boundary")
                conflicts.append(PlanIssue("scope_or_boundary", f"Source or destination is outside the selected vault scope: {exc}", file_id, target_rel))

            try:
                current_stat = source_path.stat()
                source_fingerprint = FileFingerprint(
                    size=int(row["size"]),
                    mtime_ns=int(row.get("mtime_ns") or current_stat.st_mtime_ns),
                    sha256=str(row["sha256"]),
                )
            except OSError as exc:
                current_stat = None
                source_fingerprint = FileFingerprint(int(row["size"]), int(row.get("mtime_ns") or 0), str(row["sha256"]))
                per_file_codes.append("source_unreadable")
                conflicts.append(PlanIssue("source_unreadable", f"Could not inspect source: {exc}", file_id, source_rel))

            same_path = source_rel.casefold() == target_rel.casefold()
            if same_path and source_rel == target_rel:
                skips.append(PlanIssue("already_at_destination", "Source already has the planned destination path.", file_id, source_rel))
                continue
            case_only_rename = same_path and action == "rename" and source_rel != target_rel
            if case_only_rename and destination_path.exists():
                try:
                    case_only_rename = os.path.samefile(source_path, destination_path)
                except OSError:
                    case_only_rename = False

            destination_fp = DestinationFingerprint(False)
            if destination_path.exists() and not case_only_rename:
                try:
                    dst_stat = destination_path.stat()
                    destination_fp = DestinationFingerprint(
                        True, dst_stat.st_size, dst_stat.st_mtime_ns, compute_sha256(destination_path)
                    )
                except OSError as exc:
                    destination_fp = DestinationFingerprint(True)
                    per_file_codes.append("destination_unreadable")
                    conflicts.append(PlanIssue("destination_unreadable", f"Could not fingerprint existing destination: {exc}", file_id, target_rel))
                if "destination_unreadable" not in per_file_codes:
                    per_file_codes.append("destination_exists")
                    conflicts.append(PlanIssue("destination_exists", "Destination already exists; overwriting is forbidden.", file_id, target_rel))

            target_key = target_rel.casefold()
            targets.setdefault(target_key, []).append(len(preliminary))
            existing_parent = destination_path.parent
            while existing_parent != self.vault.root_path:
                if existing_parent.is_symlink():
                    per_file_codes.append("destination_symlink_parent")
                    conflicts.append(PlanIssue("destination_symlink_parent", "Destination parent traverses a symlink/junction.", file_id, target_rel))
                    break
                existing_parent = existing_parent.parent
            if len(str(destination_path)) > 240:
                per_file_codes.append("path_too_long")
                conflicts.append(PlanIssue("path_too_long", "Destination path exceeds the safe 240-character limit.", file_id, target_rel))
            writable_parent = destination_path.parent
            while not writable_parent.exists() and writable_parent != self.vault.root_path:
                writable_parent = writable_parent.parent
            if not os.access(writable_parent, os.W_OK):
                per_file_codes.append("destination_not_writable")
                conflicts.append(PlanIssue("destination_not_writable", "Destination parent is not writable.", file_id, str(writable_parent)))
            if action == "copy" and current_stat is not None:
                estimated_bytes += int(current_stat.st_size)
            else:
                estimated_bytes += int(row["size"])

            preliminary.append({
                "file_id": file_id,
                "source": source_rel,
                "destination": target_rel,
                "action": action,
                "reason": reason,
                "source_fingerprint": source_fingerprint,
                "destination_fingerprint": destination_fp,
                "conflict_codes": per_file_codes,
            })

        for target_key, item_indexes in targets.items():
            if len(item_indexes) > 1:
                for item_index in item_indexes:
                    item = preliminary[item_index]
                    if "duplicate_planned_destination" not in item["conflict_codes"]:
                        item["conflict_codes"].append("duplicate_planned_destination")
                        conflicts.append(PlanIssue(
                            "duplicate_planned_destination", "Multiple selected files map to the same case-insensitive destination.",
                            item["file_id"], item["destination"],
                        ))

        items = tuple(PlannedFileOperation(**{
            **item,
            "conflict_codes": tuple(item["conflict_codes"]),
        }) for item in preliminary)
        now = datetime.now(timezone.utc)
        empty_digest_plan = FileOperationPlan(
            plan_id=str(uuid.uuid4()),
            vault_id=self.vault.vault_id,
            scope=scope,
            created_at=now.isoformat(),
            expires_at=(now + self.ttl).isoformat(),
            index_run_id=snapshot.index_run_id,
            selection_json=json.dumps(selection_data, sort_keys=True, ensure_ascii=False),
            route_json=json.dumps(route_data, sort_keys=True, ensure_ascii=False),
            items=items,
            conflicts=tuple(conflicts),
            skips=tuple(skips),
            warnings=tuple(warnings),
            estimated_bytes=estimated_bytes,
            digest="",
            status="preview",
        )
        digest = self._digest(empty_digest_plan.payload(include_digest=False))
        plan = replace(empty_digest_plan, digest=digest)
        with self.db.transaction():
            self.db.execute(
                """INSERT INTO file_operation_plans
                   (plan_id,vault_id,scope,created_at,expires_at,index_run_id,status,digest,plan_json)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    plan.plan_id, plan.vault_id, plan.scope, plan.created_at, plan.expires_at,
                    plan.index_run_id, plan.status, plan.digest,
                    json.dumps(plan.payload(), sort_keys=True, ensure_ascii=False, separators=(",", ":")),
                ),
            )
        return plan

    def get_plan(self, plan_id: str) -> FileOperationPlan:
        row = self.db.fetch_one(
            "SELECT plan_json,digest,status FROM file_operation_plans WHERE plan_id=? AND vault_id=?",
            (plan_id, self.vault.vault_id),
        )
        if not row:
            raise KeyError(f"Operation plan not found: {plan_id}")
        plan = FileOperationPlan.from_payload(json.loads(row["plan_json"]))
        calculated = self._digest(plan.payload(include_digest=False))
        if calculated != row["digest"] or calculated != plan.digest:
            raise ValueError(f"Operation plan integrity check failed: {plan_id}")
        if plan.status != row["status"]:
            plan = replace(plan, status=row["status"])
        if plan.status == "preview" and datetime.fromisoformat(plan.expires_at) <= datetime.now(timezone.utc):
            self.db.execute(
                "UPDATE file_operation_plans SET status='expired' WHERE plan_id=? AND status='preview'",
                (plan_id,),
            )
            self.db.conn.commit()
            plan = replace(plan, status="expired")
        return plan

    def update_status(self, plan_id: str, status: str) -> None:
        if status not in {"preview", "committing", "committed", "partial", "needs_recovery", "expired", "invalidated"}:
            raise ValueError(f"Invalid plan status: {status}")
        cursor = self.db.execute(
            "UPDATE file_operation_plans SET status=? WHERE plan_id=? AND vault_id=?",
            (status, plan_id, self.vault.vault_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"Operation plan not found: {plan_id}")
        self.db.conn.commit()

    def _validate_route(self, route: RouteSpec) -> None:
        if not route.entries:
            raise ValueError("A route requires at least one rule entry.")
        if route.fallback not in {"keep", "review"}:
            raise ValueError("Route fallback must be 'keep' or 'review'.")
        if route.group_by is not None and route.group_by not in _GROUP_KEYS:
            raise ValueError(f"Unsupported deterministic group key: {route.group_by}")
        for entry in route.entries:
            validate(entry.rule)
            if entry.action not in {"move", "copy"}:
                raise ValueError(f"Unsupported route action: {entry.action}")
            self._clean_directory(entry.destination_directory)

    def _clean_directory(self, value: str) -> tuple[str, list[tuple[str, str]]]:
        normalized = str(value or "").replace("\\", "/").strip("/")
        if not normalized:
            return "", []
        components = normalized.split("/")
        issues = []
        generated_root = self.config.generated_output_folder.replace("\\", "/").strip("/").casefold()
        if normalized.casefold() == generated_root or normalized.casefold().startswith(generated_root + "/"):
            issues.append(("generated_destination", "Generated-output paths are reserved and cannot receive routed source files."))
        for component in components:
            stem = component.split(".", 1)[0].upper()
            if component in {".", ".."} or not component.strip() or component.endswith((" ", ".")):
                issues.append(("invalid_destination_component", f"Invalid destination component: {component!r}."))
            elif stem in _WINDOWS_RESERVED:
                issues.append(("reserved_destination_name", f"Windows reserves the destination name: {component}."))
            elif len(component) > 120 or any(char in component for char in '<>:"|?*') or any(ord(char) < 32 for char in component):
                issues.append(("invalid_destination_component", f"Destination component contains an unsupported name or character: {component!r}."))
        return normalized, issues

    def _clean_filename(self, value: str) -> list[tuple[str, str]]:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            return [("invalid_filename", "Filename must be one non-empty path component.")]
        stem = value.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED or value.endswith((" ", ".")):
            return [("invalid_filename", f"Filename is invalid or reserved on Windows: {value!r}.")]
        if len(value) > 120 or any(char in value for char in '<>:"|?*') or any(ord(char) < 32 for char in value):
            return [("invalid_filename", f"Filename contains unsupported characters or is too long: {value!r}.")]
        return []

    def _join_scope(self, scope: str | None, directory: str) -> str:
        directory, errors = self._clean_directory(directory)
        if errors:
            
            directory = str(directory).replace("\\", "/").strip("/")
        prefix = scope.replace("\\", "/").strip("/") if scope else ""
        return f"{prefix}/{directory}" if prefix and directory else prefix or directory

    def _group_value(self, group_by: str, row: dict) -> str:
        if group_by == "extension":
            value = row["extension"].lstrip(".").upper() or "No Extension"
        elif group_by == "family":
            value = _FAMILY_FOLDERS.get(str(row["mime_family"]).lower(), "Other")
        elif group_by == "year":
            value = str(datetime.fromtimestamp(float(row["mtime"]), timezone.utc).year)
        elif group_by == "year-month":
            value = datetime.fromtimestamp(float(row["mtime"]), timezone.utc).strftime("%Y-%m")
        elif group_by == "size":
            size = int(row["size"])
            value = "Tiny (<10KB)" if size < 10_240 else "Small (10-100KB)" if size < 102_400 else (
                "Medium (100KB-1MB)" if size < 1_048_576 else "Large (1-10MB)" if size < 10_485_760 else "Very Large (>10MB)"
            )
        elif group_by == "first-tag":
            tag = self.db.fetch_one(
                "SELECT tag FROM file_tags WHERE file_id=? ORDER BY tag_key LIMIT 1", (row["id"],)
            )
            value = tag["tag"] if tag else "Untagged"
        else:  
            value = str(row["sha256"] or "unknown")[:2].upper()
        clean, issues = self._clean_directory(value)
        return clean.replace("/", "-") if clean else "Other"

    def _legacy_group(self, grouping: str, row: dict) -> str:
        if grouping == "file-type":
            return _EXTENSION_FOLDERS.get(str(row["extension"]).lower(), "Other")
        if grouping == "file-family":
            return _FAMILY_FOLDERS.get(str(row["mime_family"]).lower(), "Other")
        if grouping == "date-year":
            return str(datetime.fromtimestamp(float(row["mtime"]), timezone.utc).year)
        if grouping == "date-month":
            return datetime.fromtimestamp(float(row["mtime"]), timezone.utc).strftime("%Y/%B")
        if grouping == "size":
            return self._group_value("size", row)
        return "Other"

    @staticmethod
    def _digest(payload: dict) -> str:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _issue_payload(issue: PlanIssue) -> dict:
    return {"code": issue.code, "message": issue.message, "file_id": issue.file_id, "path": issue.path}
