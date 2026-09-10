"""Dependency injection container for Context Vault services.

Provides lazy initialization and caching of all services.
Manages both global services and vault-scoped services.
"""

import logging
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

                         
        self._app_db: Database | None = None
        self._vault_service: Any = None
                            
        self._vault: Vault | None = None
        self._vault_db: Database | None = None
        self._filesystem_retrieval_service: Any = None
        self._llm_client: Any = None
        self._llm_checked: bool = False

        self._rag_service: Any = None
        self._organisation_service: Any = None
        self._generation_service: Any = None
        self._audit_service: Any = None
        self._orchestrator: Any = None

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
                llm_client=self.llm_client,
                config=self._config,
            )
        return self._filesystem_retrieval_service

    @property
    def llm_client(self):
        """Ollama LLM client (may be None if unavailable)."""
        if not self._llm_checked:
            self._llm_checked = True
            try:
                from contextvault.llm.ollama_client import OllamaClient
                client = OllamaClient(
                    base_url=self._config.ollama_base_url,
                    model=self._config.ollama_model,
                    timeout=self._config.ollama_timeout,
                )
                if client.is_available():
                    self._llm_client = client
                else:
                    logger.warning(
                        "Ollama is not available. Semantic features will be disabled."
                    )
                    self._llm_client = None
            except Exception as e:
                logger.warning(f"Could not connect to Ollama: {e}")
                self._llm_client = None
        return self._llm_client

    @property
    def rag_service(self):
        """RAG service for the active vault."""
        self._require_vault()
        if self._rag_service is None:
            from contextvault.services.rag_service import RAGService
            self._rag_service = RAGService(
                llm_client=self.llm_client,
                vault=self._vault,
                retrieval_service=self.filesystem_retrieval_service,
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
                llm_client=self.llm_client,
                retriever=None,
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
                llm_client=self.llm_client,
                retrieval_service=self.filesystem_retrieval_service,
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
                    "llm_client": self.llm_client,
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
        logger.info(f"Opened vault: {vault.display_name} at {vault.root_path}")
        try:
            self.vault_service.scan_vault(vault, self.vault_db)
        except Exception as e:
            logger.warning(f"Initial scan warning on open: {e}")
        return vault

    def close_vault(self) -> None:
        """Release all vault-scoped services."""
        self._vault = None
        self._vault_db = None
        self._filesystem_retrieval_service = None
        self._rag_service = None
        self._organisation_service = None
        self._generation_service = None
        self._audit_service = None
        self._orchestrator = None
                                                         

    @property
    def has_llm(self) -> bool:
        """Check if LLM is available without triggering full init."""
        return self.llm_client is not None
