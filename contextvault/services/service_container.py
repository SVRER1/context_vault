"""Dependency injection container for Context Vault services.

Provides lazy initialization and caching of all services.
Manages both global services and vault-scoped services.
"""

import logging
import threading
from pathlib import Path
from typing import Any

from contextvault.core.config import AppConfig, get_config
from contextvault.core.vault import Vault
from contextvault.storage.database import Database

logger = logging.getLogger(__name__)


class ServiceContainer:
    """Lazy dependency injection container for all Context Vault services.

    Global services (app_db, vault_service) persist across
    vault changes. Vault-scoped services are recreated when a vault is opened.
    """

    def __init__(self, config: AppConfig | None = None):
        self._config = config or get_config()
        
        
        
        self.database_lock = threading.RLock()

        
        self._app_db: Database | None = None
        self._vault_service: Any = None
        
        self._vault: Vault | None = None
        self._vault_db: Database | None = None
        self._filesystem_retrieval_service: Any = None
        self._search_service: Any = None
        self._index_service: Any = None
        self._rule_executor: Any = None
        self._plan_service: Any = None
        self._execution_service: Any = None
        self._artifact_provider: Any = None
        self._llm_client: Any = None
        self._llm_checked: bool = False

        self._rag_service: Any = None
        self._organisation_service: Any = None
        self._generation_service: Any = None
        self._audit_service: Any = None
        self._tag_service: Any = None
        self._orchestrator: Any = None
        self.recovery_on_open: list[Any] = []

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def vault(self) -> Vault | None:
        """The currently active vault, or None."""
        return self._vault

    @property
    def app_db(self) -> Database:
        """Main application database (global, not vault-specific)."""
        if self._app_db is None:
            db_path = self._config.app_db_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._app_db = Database(db_path)
            self._app_db.initialize()
        return self._app_db

    @property
    def vault_service(self):
        """Vault lifecycle management service."""
        if self._vault_service is None:
            from contextvault.services.vault_service import VaultService
            self._vault_service = VaultService(self._config, self.app_db)
        return self._vault_service

    def _require_vault(self) -> Vault:
        """Raise if no vault is open."""
        if self._vault is None:
            raise ValueError(
                "No vault is currently open. Use open_vault() first."
            )
        return self._vault

    @property
    def vault_db(self) -> Database:
        """Database for the active vault."""
        vault = self._require_vault()
        if self._vault_db is None:
            self._vault_db = self.vault_service.get_vault_db(vault)
        return self._vault_db

    @property
    def filesystem_retrieval_service(self):
        """Filesystem-native retrieval for the active vault and explicit scope."""
        vault = self._require_vault()
        if self._filesystem_retrieval_service is None:
            from contextvault.retrieval.filesystem_service import FilesystemRetrievalService
            self._filesystem_retrieval_service = FilesystemRetrievalService(
                vault=vault,
                llm_client=None,
                ocr_client=None,
                config=self._config,
            )
        return self._filesystem_retrieval_service

    @property
    def index_service(self):
        vault = self._require_vault()
        if self._index_service is None:
            from contextvault.indexing.index_service import IndexService
            self._index_service = IndexService(vault, self.vault_db, self._config)
        return self._index_service

    @property
    def rule_executor(self):
        vault = self._require_vault()
        if self._rule_executor is None:
            from contextvault.query.executor import RuleExecutor
            self._rule_executor = RuleExecutor(vault, self.vault_db, self._config)
        return self._rule_executor

    @property
    def plan_service(self):
        vault = self._require_vault()
        if self._plan_service is None:
            from contextvault.filesystem.plan_service import PlanService
            self._plan_service = PlanService(
                vault, self.vault_db, self._config, rule_executor=self.rule_executor
            )
        return self._plan_service

    @property
    def execution_service(self):
        vault = self._require_vault()
        if self._execution_service is None:
            from contextvault.filesystem.execution_service import ExecutionService
            self._execution_service = ExecutionService(vault, self.vault_db, self.plan_service)
        return self._execution_service

    @property
    def artifact_provider(self):
        """Optional, lazy provider; creating it does not contact Ollama."""
        if self._artifact_provider is None:
            from contextvault.generation.artifact_provider import OllamaArtifactProvider
            self._artifact_provider = OllamaArtifactProvider(self._create_llm_client)
        return self._artifact_provider

    @property
    def search_service(self):
        """Deterministic indexed retrieval; does not inspect or initialize an LLM."""
        vault = self._require_vault()
        if self._search_service is None:
            from contextvault.retrieval.search_service import SearchService
            self._search_service = SearchService(
                vault=vault, db=self.vault_db, config=self._config,
                rule_executor=self.rule_executor,
            )
        return self._search_service

    @property
    def llm_client(self):
        """Legacy lazily constructed client; core services never access it."""
        return self._create_llm_client()

    def _create_llm_client(self):
        """Construct Ollama only when the artifact provider receives a request."""
        if self._llm_checked:
            return self._llm_client
        self._llm_checked = True
        try:
            from contextvault.llm.ollama_client import OllamaClient
            client = OllamaClient(
                base_url=self._config.ollama_base_url,
                model=self._config.ollama_model,
                timeout=self._config.ollama_timeout,
            )
            self._llm_client = client
        except Exception as exc:
            logger.warning("Could not connect to Ollama: %s", exc)
            self._llm_client = None
        return self._llm_client

    @property
    def rag_service(self):
        """RAG service for the active vault."""
        self._require_vault()
        if self._rag_service is None:
            from contextvault.services.rag_service import RAGService
            self._rag_service = RAGService(
                llm_client=None,
                vault=self._vault,
                search_service=self.search_service,
                artifact_provider=self.artifact_provider,
            )
        return self._rag_service

    @property
    def organisation_service(self):
        """Organisation service for the active vault."""
        self._require_vault()
        if self._organisation_service is None:
            from contextvault.services.organisation_service import OrganisationService
            self._organisation_service = OrganisationService(
                vault=self._vault,
                db=self.vault_db,
                llm_client=None,
                retriever=None,
                plan_service=self.plan_service,
                execution_service=self.execution_service,
            )
        return self._organisation_service

    @property
    def generation_service(self):
        """Generation service for the active vault."""
        self._require_vault()
        if self._generation_service is None:
            from contextvault.services.generation_service import GenerationService
            self._generation_service = GenerationService(
                vault=self._vault,
                db=self.vault_db,
                llm_client=None,
                retrieval_service=self.filesystem_retrieval_service,
                artifact_provider=self.artifact_provider,
            )
        return self._generation_service

    @property
    def audit_service(self):
        """Audit service for the active vault."""
        self._require_vault()
        if self._audit_service is None:
            from contextvault.services.audit_service import AuditService
            self._audit_service = AuditService(self.vault_db)
        return self._audit_service

    @property
    def tag_service(self):
        self._require_vault()
        if self._tag_service is None:
            from contextvault.services.tag_service import TagService
            self._tag_service = TagService(self._vault, self.vault_db, self.index_service)
        return self._tag_service

    @property
    def orchestrator(self):
        """Agent orchestrator for the active vault."""
        self._require_vault()
        if self._orchestrator is None:
            from contextvault.agent.orchestrator import Orchestrator
            self._orchestrator = Orchestrator(
                services={
                    "vault": self._vault,
                    "vault_service": self.vault_service,
                    "rag_service": self.rag_service,
                    "organisation_service": self.organisation_service,
                    "generation_service": self.generation_service,
                    "audit_service": self.audit_service,
                    "filesystem_retrieval_service": self.filesystem_retrieval_service,
                    "llm_client": None,
                    "artifact_provider": self.artifact_provider,
                    "config": self.config,
                }
            )
        return self._orchestrator

    def open_vault(self, path: str | Path) -> Vault:
        """Open a vault and prepare all vault-scoped services.

        Args:
            path: Path to the vault directory.

        Returns:
            The opened Vault object.
        """
        self.close_vault()
        vault = self.vault_service.open_vault(path)
        self._vault = vault
        try:
            from contextvault.filesystem.recovery import RecoveryService

            self.recovery_on_open = RecoveryService(
                vault, self.vault_service.get_vault_db(vault)
            ).inspect_incomplete()
            if self.recovery_on_open:
                logger.warning(
                    "Vault has %d interrupted operation batch(es) requiring inspection.",
                    len(self.recovery_on_open),
                )
        except Exception:
            self.recovery_on_open = []
            logger.exception("Could not inspect the operation journal while opening the vault.")
        logger.info(f"Opened vault: {vault.display_name} at {vault.root_path}")
        return vault

    def close_vault(self) -> None:
        """Release all vault-scoped services."""
        self._vault = None
        self._vault_db = None
        self._filesystem_retrieval_service = None
        self._search_service = None
        self._index_service = None
        self._rule_executor = None
        self._plan_service = None
        self._execution_service = None
        self._rag_service = None
        self._organisation_service = None
        self._generation_service = None
        self._audit_service = None
        self._tag_service = None
        self._orchestrator = None
        self.recovery_on_open = []
        

    @property
    def has_llm(self) -> bool:
        """Report known availability without triggering an external check."""
        return bool(self._artifact_provider and self._artifact_provider.available is True)
