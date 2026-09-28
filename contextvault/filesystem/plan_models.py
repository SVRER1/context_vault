"""Immutable routing and filesystem operation plan contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from contextvault.query.ast import RuleNode, deserialize, serialize


@dataclass(frozen=True)
class RouteEntry:
    rule: RuleNode
    destination_directory: str
    action: Literal["move", "copy"] = "move"


@dataclass(frozen=True)
class RouteSpec:
    entries: tuple[RouteEntry, ...]
    fallback: Literal["keep", "review"] = "review"
    group_by: Literal["extension", "family", "year", "year-month", "size", "first-tag", "hash-prefix"] | None = None


@dataclass(frozen=True)
class FileFingerprint:
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class DestinationFingerprint:
    exists: bool
    size: int | None = None
    mtime_ns: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class PlannedFileOperation:
    file_id: str
    source: str
    destination: str
    action: Literal["move", "copy", "rename"]
    reason: str
    source_fingerprint: FileFingerprint
    destination_fingerprint: DestinationFingerprint
    conflict_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanIssue:
    code: str
    message: str
    file_id: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class FileOperationPlan:
    plan_id: str
    vault_id: str
    scope: str | None
    created_at: str
    expires_at: str
    index_run_id: str | None
    selection_json: str
    route_json: str
    items: tuple[PlannedFileOperation, ...]
    conflicts: tuple[PlanIssue, ...]
    skips: tuple[PlanIssue, ...]
    warnings: tuple[PlanIssue, ...]
    estimated_bytes: int
    digest: str
    status: str = "preview"

    def payload(self, *, include_digest: bool = True) -> dict:
        value = {
            "plan_id": self.plan_id,
            "vault_id": self.vault_id,
            "scope": self.scope,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "index_run_id": self.index_run_id,
            "selection": json.loads(self.selection_json),
            "route": json.loads(self.route_json),
            "items": [
                {
                    "file_id": item.file_id,
                    "source": item.source,
                    "destination": item.destination,
                    "action": item.action,
                    "reason": item.reason,
                    "source_fingerprint": {
                        "size": item.source_fingerprint.size,
                        "mtime_ns": item.source_fingerprint.mtime_ns,
                        "sha256": item.source_fingerprint.sha256,
                    },
                    "destination_fingerprint": {
                        "exists": item.destination_fingerprint.exists,
                        "size": item.destination_fingerprint.size,
                        "mtime_ns": item.destination_fingerprint.mtime_ns,
                        "sha256": item.destination_fingerprint.sha256,
                    },
                    "conflict_codes": list(item.conflict_codes),
                }
                for item in self.items
            ],
            "conflicts": [_issue_data(issue) for issue in self.conflicts],
            "skips": [_issue_data(issue) for issue in self.skips],
            "warnings": [_issue_data(issue) for issue in self.warnings],
            "estimated_bytes": self.estimated_bytes,
            "status": self.status,
        }
        if include_digest:
            value["digest"] = self.digest
        return value

    def to_organisation_plan(self):
        """Compatibility projection for existing preview renderers."""
        from contextvault.core.models import OrganisationPlan, PlannedOperation

        conflicted = {issue.file_id for issue in self.conflicts if issue.file_id}
        operations = [
            PlannedOperation(
                type=item.action, source=item.source, destination=item.destination,
                reason=item.reason, confidence=1.0,
            )
            for item in self.items if item.file_id not in conflicted
        ]
        warnings = [issue.message for issue in (*self.conflicts, *self.warnings)]
        untouched = [issue.path for issue in self.skips if issue.path]
        directories = sorted({
            item.destination.rpartition("/")[0]
            for item in self.items
            if item.file_id not in conflicted and item.destination.rpartition("/")[0]
        })
        return OrganisationPlan(
            directories_to_create=directories,
            operations=operations,
            warnings=warnings,
            untouched_files=untouched,
            source_scope=self.scope,
        )

    @classmethod
    def from_payload(cls, value: dict) -> "FileOperationPlan":
        items = tuple(
            PlannedFileOperation(
                file_id=item["file_id"], source=item["source"], destination=item["destination"],
                action=item["action"], reason=item["reason"],
                source_fingerprint=FileFingerprint(**item["source_fingerprint"]),
                destination_fingerprint=DestinationFingerprint(**item["destination_fingerprint"]),
                conflict_codes=tuple(item.get("conflict_codes", ())),
            )
            for item in value.get("items", ())
        )
        return cls(
            plan_id=value["plan_id"], vault_id=value["vault_id"], scope=value.get("scope"),
            created_at=value["created_at"], expires_at=value["expires_at"],
            index_run_id=value.get("index_run_id"),
            selection_json=json.dumps(value.get("selection", {}), sort_keys=True, ensure_ascii=False),
            route_json=json.dumps(value.get("route", {}), sort_keys=True, ensure_ascii=False),
            items=items,
            conflicts=tuple(_issue_from_data(item) for item in value.get("conflicts", ())),
            skips=tuple(_issue_from_data(item) for item in value.get("skips", ())),
            warnings=tuple(_issue_from_data(item) for item in value.get("warnings", ())),
            estimated_bytes=int(value.get("estimated_bytes", 0)),
            digest=value["digest"], status=value.get("status", "preview"),
        )


def _issue_data(issue: PlanIssue) -> dict:
    return {"code": issue.code, "message": issue.message, "file_id": issue.file_id, "path": issue.path}


def _issue_from_data(value: dict) -> PlanIssue:
    return PlanIssue(value["code"], value["message"], value.get("file_id"), value.get("path"))


def route_to_data(route: RouteSpec) -> dict:
    return {
        "entries": [
            {"rule": serialize(entry.rule), "destination_directory": entry.destination_directory, "action": entry.action}
            for entry in route.entries
        ],
        "fallback": route.fallback,
        "group_by": route.group_by,
    }


def route_from_data(value: dict) -> RouteSpec:
    return RouteSpec(
        entries=tuple(
            RouteEntry(
                rule=deserialize(entry["rule"]),
                destination_directory=entry["destination_directory"],
                action=entry.get("action", "move"),
            )
            for entry in value.get("entries", ())
        ),
        fallback=value.get("fallback", "review"),
        group_by=value.get("group_by"),
    )
