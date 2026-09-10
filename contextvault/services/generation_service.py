"""Generation service for creating derived knowledge assets.

Generates summaries, study guides, flashcards, quizzes, and other
content from vault files. Never modifies existing files.
"""

import logging
from datetime import datetime
from typing import Any

from contextvault.core.config import get_config
from contextvault.core.exceptions import OllamaUnavailableError
from contextvault.core.models import GeneratedAsset
from contextvault.core.vault import Vault
from contextvault.generation.generator import ContentGenerator
from contextvault.storage.database import Database

logger = logging.getLogger(__name__)


class GenerationService:
    """Service for generating content using LLMs and vault context."""

    def __init__(self, vault: Vault, db: Database, llm_client: Any, retriever: Any = None, retrieval_service: Any = None):
        self.vault = vault
        self.db = db
        self.llm_client = llm_client
        self.retriever = retriever
        self.retrieval_service = retrieval_service

    def generate(
        self,
        asset_type: str,
        topic: str | None = None,
        count: int | None = None,
        filename: str | None = None,
        subfolder: str | None = None,
    ) -> GeneratedAsset:
        """Generate a new content asset from vault knowledge.

        Args:
            asset_type: Type of asset (summary, study-guide, revision-notes,
                        flashcards, quiz, timeline, vault-report).
            topic: Optional topic focus.
            count: Number of items (for flashcards/quiz).
            filename: Optional output filename.

        Returns:
            GeneratedAsset with metadata about the created file.

        Raises:
            OllamaUnavailableError: If LLM is not available.
        """
        if self.llm_client is None:
            raise OllamaUnavailableError(
                "Local LLM is not available for generation. "
                "Please ensure Ollama is running."
            )

        generator = ContentGenerator(
            llm_client=self.llm_client,
            retriever=self.retriever,
            retrieval_service=self.retrieval_service,
            vault=self.vault,
            db=self.db,
            subfolder=subfolder,
        )

        asset = generator.generate(
            asset_type=asset_type,
            topic=topic,
            count=count,
            filename=filename,
        )

                            
        try:
            self.db.execute(
                """INSERT INTO generated_assets 
                   (id, vault_id, asset_type, title, filename, relative_path, created_at, source_chunks, source_files, source_scope)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    asset.id,
                    asset.vault_id,
                    asset.asset_type,
                    asset.title,
                    asset.filename,
                    asset.relative_path,
                    asset.created_at.isoformat(),
                    ",".join(asset.source_chunks),
                    ",".join(asset.source_files),
                    asset.source_scope,
                ),
            )
            self.db.conn.commit()
        except Exception as e:
            logger.warning(f"Could not record generated asset in DB: {e}")

        return asset

    def list_generated(self) -> list[GeneratedAsset]:
        """List all generated assets for this vault."""
        rows = self.db.fetch_all(
            "SELECT * FROM generated_assets WHERE vault_id = ? ORDER BY created_at DESC",
            (self.vault.vault_id,),
        )
        assets = []
        for row in rows:
            try:
                assets.append(GeneratedAsset(
                    id=row["id"],
                    vault_id=row["vault_id"],
                    asset_type=row["asset_type"],
                    title=row["title"],
                    filename=row["filename"],
                    relative_path=row["relative_path"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    source_chunks=row.get("source_chunks", "").split(",") if row.get("source_chunks") else [],
                    source_files=row.get("source_files", "").split(",") if row.get("source_files") else [],
                    source_scope=row.get("source_scope"),
                ))
            except Exception as e:
                logger.warning(f"Could not load generated asset: {e}")
        return assets
