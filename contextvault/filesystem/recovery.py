"""Read-only inspection and explicit recovery for interrupted journal batches."""

from __future__ import annotations

import json
from dataclasses import dataclass

from contextvault.core.vault import Vault
from contextvault.filesystem.execution_service import ExecutionService, _now
from contextvault.filesystem.publication import publish_no_replace
from contextvault.indexing.fingerprint import compute_sha256
from contextvault.storage.database import Database


@dataclass(frozen=True)
class RecoveryAssessment:
    item_id: str
    state: str
    classification: str
    advice: str
    source_exists: bool
    destination_exists: bool
    temp_exists: bool
    temp_matches: bool = False


class RecoveryService:
    """Inspect journal entries from observed paths and hashes, never status alone."""

    def __init__(self, vault: Vault, db: Database):
        self.vault = vault
        self.db = db
        self.executor = ExecutionService(vault, db)

    def history(self, *, limit: int = 50) -> list[dict]:
        batches = self.db.fetch_all(
            """SELECT b.*,p.scope,p.created_at AS plan_created,p.plan_json,p.digest
               FROM operation_batches_v3 b JOIN file_operation_plans p ON p.plan_id=b.plan_id
               WHERE b.vault_id=? ORDER BY b.created_at DESC LIMIT ?""",
            (self.vault.vault_id, max(1, min(500, int(limit)))),
        )
        for batch in batches:
            plan = json.loads(batch.pop("plan_json"))
            batch["selection"] = plan.get("selection")
            batch["route"] = plan.get("route")
            batch["digest"] = plan.get("digest")
            batch["items"] = self.db.fetch_all(
                "SELECT * FROM operation_items_v3 WHERE batch_id=? ORDER BY plan_item_index",
                (batch["batch_id"],),
            )
            batch["assessment"] = self.inspect_batch(batch["batch_id"])
        return batches

    def inspect_batch(self, batch_id: str) -> list[RecoveryAssessment]:
        batch = self.db.fetch_one(
            "SELECT * FROM operation_batches_v3 WHERE batch_id=? AND vault_id=?",
            (batch_id, self.vault.vault_id),
        )
        if not batch:
            raise KeyError(f"Operation batch not found: {batch_id}")
        results = []
        for row in self.db.fetch_all(
            "SELECT * FROM operation_items_v3 WHERE batch_id=? ORDER BY plan_item_index",
            (batch_id,),
        ):
            source_raw = self.vault.root_path / row["source_path"]
            dest_raw = self.vault.root_path / row["destination_path"]
            temp_raw = self.vault.root_path / row["temp_path"] if row.get("temp_path") else None
            try:
                source = self.vault.validate_path(source_raw)
                dest = self.vault.validate_path(dest_raw)
                if source_raw.is_symlink() or dest_raw.is_symlink():
                    raise ValueError("Journal path is now a symlink.")
                if temp_raw is not None:
                    temp = self.vault.validate_path(temp_raw)
                    if temp_raw.is_symlink():
                        raise ValueError("Journal temporary path is now a symlink.")
                else:
                    temp = None
            except (OSError, ValueError, RuntimeError):
                results.append(RecoveryAssessment(row["item_id"], row["state"], "manual_review",
                    "Journal path is invalid or crosses a symlink/boundary; inspect without mutating.",
                    source_raw.exists(), dest_raw.exists(), bool(temp_raw and temp_raw.exists()), False))
                continue
            source_exists = source.exists()
            dest_exists = dest.exists()
            temp_exists = bool(temp and temp.exists())
            if row["state"] == "committed":
                results.append(RecoveryAssessment(row["item_id"], row["state"], "complete",
                    "No recovery action is needed.", source_exists, dest_exists, temp_exists, False))
                continue
            source_ok = source_exists and source.is_file() and compute_sha256(source) == row["before_hash"]
            dest_ok = dest_exists and dest.is_file() and compute_sha256(dest) == (row.get("after_hash") or row["before_hash"])
            temp_ok = bool(temp_exists and temp and temp.is_file() and
                           compute_sha256(temp) == row["before_hash"])
            if dest_ok and not source_exists and row["action"] != "copy":
                classification, advice = "safe_to_finalize", "Destination and source state match the journal; finalize index metadata."
            elif temp_exists and not temp_ok:
                classification, advice = "manual_review", "Temporary file does not match the journaled source hash; retain it for inspection."
            elif row["action"] == "rename" and temp_ok and not source_exists and not dest_exists:
                classification, advice = "safe_to_finalize", "The verified file is in its reserved case-rename path; publish the requested spelling."
            elif source_ok and not dest_exists and row["state"] in {"prepared", "started", "copying", "needs_recovery"}:
                classification, advice = "safe_to_retry", "Source is unchanged and destination is absent; a reviewed retry can continue."
            elif row["action"] == "copy" and source_ok and dest_ok:
                classification, advice = "manual_review", "Both source and destination exist; preserve both until provenance is reviewed."
            elif source_ok and dest_ok:
                classification, advice = "manual_review", "Both paths exist; do not remove either file automatically."
            elif not source_exists and not dest_exists:
                classification, advice = "manual_review", "Neither source nor destination exists; locate the original bytes before retrying."
            elif temp_exists and not source_ok and not dest_ok:
                classification, advice = "manual_review", "Only a temporary copy remains or the source changed; retain it for inspection."
            else:
                classification, advice = "manual_review", "Observed paths or hashes differ from the journal; no automatic mutation is safe."
            results.append(RecoveryAssessment(row["item_id"], row["state"], classification, advice,
                                              source_exists, dest_exists, temp_exists, temp_ok))
        return results

    def inspect_incomplete(self) -> list[tuple[str, list[RecoveryAssessment]]]:
        rows = self.db.fetch_all(
            "SELECT batch_id FROM operation_batches_v3 WHERE vault_id=? AND status NOT IN ('committed','undone') ORDER BY created_at",
            (self.vault.vault_id,),
        )
        return [(row["batch_id"], self.inspect_batch(row["batch_id"])) for row in rows]

    def recover(self, batch_id: str, *, approved: bool) -> dict:
        """Retry or finalize items only after explicit approval and fresh hash checks."""
        if not approved:
            raise PermissionError("Explicit approval is required for recovery actions.")
        batch = self.db.fetch_one(
            "SELECT * FROM operation_batches_v3 WHERE batch_id=? AND vault_id=?",
            (batch_id, self.vault.vault_id),
        )
        if not batch:
            raise KeyError(f"Operation batch not found: {batch_id}")
        plan = self.executor.plans.get_plan(batch["plan_id"])
        assessment = {item.item_id: item for item in self.inspect_batch(batch_id)}
        results = []
        for row in self.db.fetch_all(
            "SELECT * FROM operation_items_v3 WHERE batch_id=? ORDER BY plan_item_index",
            (batch_id,),
        ):
            status = assessment[row["item_id"]]
            if status.classification == "complete":
                results.append((row["item_id"], "complete"))
                continue
            if status.classification == "manual_review":
                results.append((row["item_id"], "manual_review"))
                continue
            item = plan.items[int(row["plan_item_index"])]
            try:
                if status.classification == "safe_to_finalize":
                    destination = self.vault.root_path / item.destination
                    temp_path = self.vault.root_path / row["temp_path"] if row.get("temp_path") else None
                    if item.action == "rename" and not destination.exists() and temp_path and temp_path.exists():
                        publish_no_replace(temp_path, destination)
                        if compute_sha256(destination) != item.source_fingerprint.sha256:
                            raise RuntimeError("Recovered case-rename destination failed its hash check.")
                    self.executor._update_index(item, destination)
                    self.executor._set_item(row["item_id"], "committed", index_applied=True,
                                            result_file_id=item.file_id)
                elif status.classification == "safe_to_retry":
                    self.executor._execute_item(batch_id, row["item_id"], item)
                results.append((row["item_id"], "committed"))
            except Exception as exc:
                self.executor._set_item(row["item_id"], "needs_recovery", error=str(exc))
                results.append((row["item_id"], f"needs_recovery: {exc}"))
        rows = self.db.fetch_all("SELECT state FROM operation_items_v3 WHERE batch_id=?", (batch_id,))
        complete = bool(rows) and all(row["state"] == "committed" for row in rows)
        self.executor._set_batch(batch_id, "committed" if complete else "needs_recovery")
        if complete:
            self.executor.plans.update_status(batch["plan_id"], "committed")
        return {"batch_id": batch_id, "status": "committed" if complete else "needs_recovery", "items": results}
