"""Scope-safe three-valued evaluation of the shared rule AST."""

from __future__ import annotations

from dataclasses import dataclass

from contextvault.core.config import AppConfig, get_config
from contextvault.core.vault import Vault
from contextvault.indexing.index_service import IndexService
from contextvault.query.ast import All, Any, Not, Predicate, RuleNode
from contextvault.query.planner import PredicateTruth, QueryPlanner
from contextvault.query.results import SelectionResult
from contextvault.query.validation import validate
from contextvault.retrieval.filesystem_policy import is_ignored_source_path, validate_source_scope
from contextvault.storage.database import Database


@dataclass(frozen=True)
class SourceUniverse:
    rows_by_id: dict[str, dict]
    index_run_id: str | None
    index_status: str
    diagnostics: tuple[str, ...]

    @property
    def file_ids(self) -> frozenset[str]:
        return frozenset(self.rows_by_id)


class RuleExecutor:
    """Evaluate selection rules over an indexed, canonical in-scope universe."""

    def __init__(self, vault: Vault, db: Database, config: AppConfig | None = None):
        self.vault = vault
        self.db = db
        self.config = config or get_config()

    def select(
        self,
        rule: RuleNode,
        *,
        scope: str | None = None,
        reconcile: bool = True,
        force_reconcile: bool = False,
        candidate_limit: int = 20_000,
    ) -> SelectionResult:
        snapshot = self.prepare_universe(
            scope=scope, reconcile=reconcile, force_reconcile=force_reconcile
        )
        return self.evaluate_prepared(rule, snapshot, candidate_limit=candidate_limit)

    def prepare_universe(
        self,
        *,
        scope: str | None = None,
        reconcile: bool = True,
        force_reconcile: bool = False,
    ) -> SourceUniverse:
        root = validate_source_scope(self.vault, scope, self.config.generated_output_folder)
        index_run_id = None
        index_status = "complete"
        diagnostics: list[str] = []
        if reconcile:
            index_stats = IndexService(self.vault, self.db, self.config).reconcile(
                                                                              
                                                                             
                force=force_reconcile
            )
            index_run_id = index_stats.get("index_run_id")
            index_status = index_stats.get("status", "failed")
            if index_status != "complete":
                diagnostics.append(
                    f"Index reconciliation status is {index_status}; unavailable files are treated as unknown."
                )

        rows = self.db.fetch_all("SELECT * FROM files WHERE vault_id=?", (self.vault.vault_id,))
        rows_by_id: dict[str, dict] = {}
        for row in rows:
            relative = row.get("relative_path") or ""
            try:
                if not relative or is_ignored_source_path(
                    self.vault.root_path / relative, self.config.generated_output_folder
                ):
                    continue
                candidate = self.vault.validate_path(self.vault.root_path / relative)
                candidate.relative_to(root)
                if candidate.is_symlink():
                    continue
            except (OSError, ValueError, RuntimeError):
                continue
            rows_by_id[row["id"]] = row

        return SourceUniverse(rows_by_id, index_run_id, index_status, tuple(diagnostics))

    def evaluate_prepared(
        self, rule: RuleNode, snapshot: SourceUniverse, *, candidate_limit: int = 20_000
    ) -> SelectionResult:
        canonical = validate(rule)
        rows_by_id = snapshot.rows_by_id
        universe = snapshot.file_ids
        diagnostics = list(snapshot.diagnostics)
        index_run_id = snapshot.index_run_id
        index_status = snapshot.index_status
        if index_status == "failed":
            return SelectionResult(
                matched_ids=(),
                unknown_ids=self._ordered(universe, rows_by_id),
                excluded_ids=(),
                diagnostics=tuple(diagnostics),
                index_run_id=index_run_id,
            )

        planner = QueryPlanner(self.db, self.vault.vault_id, candidate_limit=candidate_limit)
        true_ids, unknown_ids = self._evaluate(canonical, universe, rows_by_id, planner)
        diagnostics.extend(planner.diagnostics)
        if index_status == "partial":
            diagnostics.append("Some file reads failed; affected content assertions remain unknown.")
        return SelectionResult(
            matched_ids=self._ordered(true_ids, rows_by_id),
            unknown_ids=self._ordered(unknown_ids, rows_by_id),
            excluded_ids=self._ordered(universe - true_ids - unknown_ids, rows_by_id),
            diagnostics=tuple(diagnostics),
            index_run_id=index_run_id,
        )

    @classmethod
    def _evaluate(cls, node: RuleNode, universe, rows_by_id, planner: QueryPlanner):
        if isinstance(node, Predicate):
            result = planner.evaluate(node, universe, rows_by_id)
            return set(result.true_ids), set(result.unknown_ids)
        if isinstance(node, Not):
            child_true, child_unknown = cls._evaluate(node.child, universe, rows_by_id, planner)
            return set(universe - child_true - child_unknown), child_unknown

        child_results = [cls._evaluate(child, universe, rows_by_id, planner) for child in node.children]
        if isinstance(node, All):
            true_ids = set(universe)
            possible_ids = set(universe)
            for child_true, child_unknown in child_results:
                true_ids.intersection_update(child_true)
                possible_ids.intersection_update(child_true | child_unknown)
            return true_ids, possible_ids - true_ids
        if isinstance(node, Any):
            true_ids: set[str] = set()
            possible_ids: set[str] = set()
            for child_true, child_unknown in child_results:
                true_ids.update(child_true)
                possible_ids.update(child_true | child_unknown)
            return true_ids, possible_ids - true_ids
        raise TypeError(f"Unsupported query node: {type(node).__name__}")

    @staticmethod
    def _ordered(file_ids, rows_by_id):
        return tuple(sorted(file_ids, key=lambda file_id: (rows_by_id[file_id]["path_key"], file_id)))
