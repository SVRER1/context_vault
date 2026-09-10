import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Any
from collections import Counter

from contextvault.core.models import GeneratedAsset, Citation, SearchResult
from contextvault.core.config import get_config
from contextvault.core.vault import Vault
from contextvault.core.exceptions import ContextVaultError
from contextvault.llm.client import LLMClient
from contextvault.storage.database import Database
from contextvault.retrieval.citations import CitationBuilder
from contextvault.retrieval.filesystem_models import RetrievalRequest
from contextvault.generation.writers import FileWriter
from contextvault.llm.prompts import (
    SUMMARY_PROMPT, STUDY_GUIDE_PROMPT, FLASHCARD_PROMPT, QUIZ_PROMPT, GENERATION_PROMPT
)

class ContentGenerator:
    def __init__(self, llm_client: Optional[LLMClient], retriever: Any, vault: Vault, db: Database, subfolder: str | None = None, retrieval_service=None):
        self.llm_client = llm_client
        self.retriever = retriever
        self.retrieval_service = retrieval_service
        self.vault = vault
        self.db = db
        self.subfolder = vault.scope_relative_path(subfolder)
        self.writer = FileWriter()

    def generate(
        self,
        asset_type: str,
        topic: Optional[str] = None,
        count: Optional[int] = None,
        filename: Optional[str] = None
    ) -> GeneratedAsset:
        query = topic if topic else "overview summary"
        
                                                                             
                                                                              
                                    
        chunks: List[SearchResult] = []
        evidence_document = None
        if self.retrieval_service is not None:
            request = RetrievalRequest(
                query=query,
                vault_id=self.vault.vault_id,
                source_scope=self.subfolder,
                operation="generate",
                output_type=asset_type,
                context_budget=get_config().retrieval_context_budget,
                max_rounds=get_config().retrieval_max_rounds,
                max_candidates=get_config().retrieval_max_candidates,
                max_deep_reads=get_config().retrieval_max_deep_reads,
                max_bytes_per_read=get_config().retrieval_max_bytes_per_read,
            )
            evidence_document = self.retrieval_service.retrieve(request)
            context = evidence_document.markdown
        elif self.retriever:
            try:
                retrieve_args = dict(query=query, vault_id=self.vault.vault_id, top_k=8, rerank_k=5)
                if self.subfolder:
                    retrieve_args["subfolder"] = self.subfolder
                chunks = self.retriever.retrieve(**retrieve_args)
            except Exception:
                pass
            context = self._build_generation_material(chunks)
        else:
            context = "No relevant context found in vault."
        
                          
        asset_lower = asset_type.lower().replace("_", "-")
        count_val = count or 10
        
        if "flashcard" in asset_lower:
            prompt = FLASHCARD_PROMPT.format(count=count_val, topic=query, material=context)
        elif "quiz" in asset_lower:
            prompt = QUIZ_PROMPT.format(count=count_val, topic=query, material=context)
        elif "study" in asset_lower:
            prompt = STUDY_GUIDE_PROMPT.format(topic=query, material=context)
        elif "revision" in asset_lower or "notes" in asset_lower:
            from contextvault.llm.prompts import REVISION_NOTES_PROMPT
            prompt = REVISION_NOTES_PROMPT.format(topic=query, material=context)
        elif "timeline" in asset_lower:
            from contextvault.llm.prompts import TIMELINE_PROMPT
            prompt = TIMELINE_PROMPT.format(topic=query, material=context)
        elif "report" in asset_lower:
            from contextvault.llm.prompts import VAULT_REPORT_PROMPT
            prompt = VAULT_REPORT_PROMPT.format(material=context)
        elif "summary" in asset_lower:
            prompt = SUMMARY_PROMPT.format(content=context)
        else:
            prompt = SUMMARY_PROMPT.format(content=context)

                                                            
        if evidence_document is not None and not evidence_document.sufficient:
            content = (
                f"# {asset_type.replace('-', ' ').title()}: {query}\n\n"
                f"{evidence_document.insufficiency_reason or 'The selected source scope does not contain enough evidence.'}\n"
            )
        elif self.llm_client and self.llm_client.is_available():
            try:
                from contextvault.llm.prompts import SYSTEM_ASSISTANT
                content = self.llm_client.generate(prompt, system=SYSTEM_ASSISTANT, temperature=0.2)
            except Exception:
                content = f"# {asset_type.title()}: {query}\n\n## Content Overview\n\n{context}\n"
        else:
            content = f"# {asset_type.title()}: {query}\n\n_Generated without active LLM based on indexed vault material._\n\n## Summary of Retrieved Material\n\n{context}\n"

                      
        citation_items = evidence_document.passages if evidence_document is not None else chunks
        citations = CitationBuilder.build_citations(citation_items)

                             
        title = f"{asset_type.replace('-', ' ').title()}" + (f" - {topic}" if topic else "")
        out_path = self._get_output_path(self.vault, filename, asset_type)
        final_path = self.writer.write_markdown(content, out_path, title, citations)

        rel_path = self.vault.relative_path(final_path)

        asset = GeneratedAsset(
            id=str(uuid.uuid4()),
            vault_id=self.vault.vault_id,
            asset_type=asset_type,
            title=title,
            filename=final_path.name,
            relative_path=rel_path,
            created_at=datetime.now(),
            source_chunks=[] if evidence_document is not None else [c.file_id for c in chunks if c.file_id],
            source_files=list(dict.fromkeys(
                p.relative_path for p in evidence_document.passages
            )) if evidence_document else [c.relative_path for c in chunks if c.relative_path],
            source_scope=self.subfolder,
        )
        return asset

    def _build_generation_material(self, chunks: List[SearchResult]) -> str:
        """Give the model a corpus profile before supplying retrieved evidence."""
        rows = self.db.get_all_files(self.vault.vault_id)
        if self.subfolder:
            scope_prefix = self.subfolder.replace("\\", "/").rstrip("/") + "/"
            rows = [
                row for row in rows
                if row.get("relative_path", "").replace("\\", "/").startswith(scope_prefix)
            ]

        family_counts = Counter(row.get("mime_family", "unknown") for row in rows)
        profile_lines = [
            "SOURCE CORPUS PROFILE",
            f"Scope: {self.subfolder or 'entire vault'}",
            f"Files in scope: {len(rows)}",
            "File families: " + (
                ", ".join(f"{family}={count}" for family, count in sorted(family_counts.items()))
                if family_counts else "none"
            ),
            "Matched sources:",
        ]

        seen_paths = set()
        for chunk in chunks:
            path = chunk.relative_path
            if path in seen_paths:
                continue
            seen_paths.add(path)
            row = next((item for item in rows if item.get("relative_path") == path), {})
            source_kind = row.get("mime_family", "unknown")
            if source_kind == "image":
                source_kind += "; text is OCR-derived"
            profile_lines.append(
                f"- {path} ({source_kind}, parser={row.get('parser') or 'unknown'}, "
                f"parse_status={row.get('parse_status') or 'unknown'})"
            )
        if not seen_paths:
            profile_lines.append("- none")

        evidence = "\n---\n".join(
            f"[{c.relative_path}]\n{c.snippet}" for c in chunks
        ) if chunks else "No relevant context found in vault."
        return "\n".join(profile_lines) + "\n\nRETRIEVED EVIDENCE\n" + evidence

    def _get_output_path(self, vault: Vault, filename: Optional[str], asset_type: str) -> Path:
        gen_dir = vault.generated_dir
        gen_dir.mkdir(parents=True, exist_ok=True)
        
        base_name = filename or f"{asset_type.replace('-', '_').title()}.md"
        candidate = Path(base_name)
        if candidate.is_absolute() or candidate.name != base_name or base_name in (".", ".."):
            raise ContextVaultError("Generated filename must be a single file name inside the vault Generated folder.")
        if not base_name.endswith('.md') and not base_name.endswith('.txt'):
            base_name += '.md'
             
        target = vault.validate_path(gen_dir / base_name)
        counter = 2
        while target.exists():
            target = gen_dir / f"{target.stem}_{counter}{target.suffix}"
            counter += 1
            
        return target
