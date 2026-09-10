"""Agent orchestrator connecting intents and small-model tool calls to real operations."""

import logging
import re
from typing import Any, Dict, List, Optional
from pathlib import Path

from contextvault.agent.intent import IntentRouter
from contextvault.agent.result import AgentResult
from contextvault.core.vault import Vault
from contextvault.organisation.rules import OrganisationRules
from contextvault.tools.peeker import ShallowPeeker
from contextvault.tools.charts import ChartGenerator
from contextvault.generation.pdf_compiler import PDFCompiler
from contextvault.tools import build_default_tool_registry

logger = logging.getLogger(__name__)


class Orchestrator:
    """Central agent orchestrator for natural language interaction and tool dispatch."""

    def __init__(self, services: Dict[str, Any]):
        self.services = services
        self.llm_client = services.get("llm_client")
        self.rag_service = services.get("rag_service")
        self.organisation_service = services.get("organisation_service")
        self.generation_service = services.get("generation_service")
        self.vault_service = services.get("vault_service")
        self.tool_registry = build_default_tool_registry(
            services.get("vault"), services
        ) if services.get("vault") else None

    def handle_query(self, user_input: str, vault: Vault, subfolder: str | None = None) -> AgentResult:
        """Analyze natural language input, route to appropriate deterministic tool or RAG, and return rich result."""
        clean_input = user_input.strip()
        if not clean_input:
            return AgentResult(result_type="answer", content="Please enter a question or command.")

        lower = clean_input.lower()

        try:
                                                                            
            if any(w in lower for w in ["peek", "inspect directory", "inspect folder", "read 10 lines", "read 20 lines", "preview files"]):
                return self._handle_peek(vault, subfolder=subfolder)

                                                                                     
            if any(w in lower for w in ["ocr", "read text from image", "extract text from image"]):
                return self._handle_ocr(clean_input, vault, subfolder=subfolder)

                                                            
            if any(w in lower for w in ["chart", "plot", "graph", "visualize", "bar chart", "line chart", "pie chart"]):
                return self._handle_chart(clean_input, vault, subfolder=subfolder)

                                                       
            classification = IntentRouter.classify(clean_input, self.llm_client)
            intent = classification.intent
            params = classification.parameters or {}

            logger.info(f"Routed query '{clean_input}' to intent: {intent} (confidence: {classification.confidence:.2f})")

            if intent == "peek_directory":
                return self._handle_peek(vault, subfolder=subfolder)
            elif intent == "generate_chart":
                return self._handle_chart(clean_input, vault, subfolder=subfolder)
            elif intent == "search":
                return self._handle_search(clean_input, params, vault, subfolder=subfolder)
            elif intent == "duplicates":
                return self._handle_duplicates(vault, subfolder=subfolder)
            elif intent == "organise":
                return self._handle_organise(clean_input, vault, subfolder=subfolder)
            elif intent == "capabilities":
                return self._handle_capabilities(vault)
            elif intent == "generate":
                return self._handle_generate(clean_input, params, vault, subfolder=subfolder)
            elif intent == "status":
                return self._handle_status(vault)
            else:
                                               
                return self._handle_rag(clean_input, vault, subfolder=subfolder)

        except Exception as e:
            logger.error(f"Orchestration error for '{clean_input}': {e}", exc_info=True)
            return AgentResult(
                result_type="error",
                content=f"An error occurred while executing your request: {e}",
                errors=[str(e)],
            )

    def _handle_ocr(self, user_input: str, vault: Vault, subfolder: str | None = None) -> AgentResult:
        """Run OCR on the named image, or the only in-scope image available."""
        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
        images = [
            p for ext in image_extensions for p in vault.root_path.rglob(f"*{ext}")
            if vault.is_in_scope(p, subfolder)
            and not any(part in {".git", ".venv", ".contextvault", vault.generated_dir.name} for part in p.parts)
        ]
        lower = user_input.lower()
        target = next((p for p in images if p.name.lower() in lower or p.stem.lower() in lower), None)
        if target is None and len(images) == 1:
            target = images[0]
        if target is None:
            return AgentResult(
                result_type="error",
                content="Please name an image, or keep exactly one image in the selected scope for OCR.",
            )

        relative_path = vault.relative_path(target)
        if self.tool_registry:
            result = self.tool_registry.execute("ocr_image", {"file_path": relative_path, "subfolder": subfolder or ""})
            if not result.success:
                return AgentResult(result_type="error", content=result.error or result.message, errors=[result.error or result.message])
            data = result.data
        else:
            return AgentResult(result_type="error", content="OCR tool registry is unavailable.")

        text = data.get("text", "").strip()
        status = data.get("metadata", {}).get("ocr_status", "unknown")
        backend = data.get("metadata", {}).get("ocr_backend", "none")
        content = (
            f"### OCR Result: `{relative_path}`\n"
            f"- **Backend**: `{backend}`\n"
            f"- **Status**: `{status}`\n\n"
            f"{text or '_No readable text was extracted._'}"
        )
        return AgentResult(result_type="ocr_result", content=content, data=data)

    def _handle_capabilities(self, vault: Vault) -> AgentResult:
        """Report implemented and reachable agent capabilities, not marketing claims."""
        config = self.services.get("config")
        model = config.ollama_model if config else "gemma4:e2b"
        llm_online = bool(self.llm_client and self.llm_client.is_available())
        registry_tools = self.tool_registry.list_tools() if self.tool_registry else []

        lines = [
            "### Actual Agent Tooling Report",
            "",
            "This report describes executable code paths in the active vault, including limits and unavailable dependencies.",
            "",
            "#### Runtime",
            f"- **LLM**: `{model}` — {'online' if llm_online else 'offline'} via Ollama.",
            "- **Retrieval**: filesystem-native survey, lexical/path candidate discovery, selective reading, and query-scoped evidence Markdown. No embeddings or vector database are required.",
            "- **Execution model**: deterministic intent routing calls Python services; the LLM selects candidates and writes grounded text. It does not receive unrestricted shell or filesystem access.",
            "",
            "#### Reachable operations",
            "- **Ask/search**: live filesystem survey, path/lexical/metadata ranking, bounded previews, selective deep reading, and source citations. It does not require prior indexing.",
            "- **Generate artifacts**: summaries, study guides, revision notes, flashcards, quizzes, timelines, vault reports, Markdown, and styled PDFs from retrieved vault context. It does not independently research the web.",
            "- **Inspect**: shallow directory/file previews capped at 10–20 lines per file.",
            "- **Charts**: inspect CSV/XLSX data and generate bar, line, scatter, or pie PNGs; column inference is deterministic.",
            "- **Organise**: preview and apply file moves by type/family/date/size/semantic rules, with collision checks, hash verification, audit history, and undo.",
            "- **Duplicates**: exact SHA-256 duplicates and probable filename/version revisions.",
            "- **Images**: OCR runs when an image is selected for evidence or through the explicit OCR tool. Tesseract is preferred, with Ollama vision fallback.",
            "",
            "#### Registered tool declarations",
        ]
        if registry_tools:
            for tool in registry_tools:
                lines.append(f"- `{tool.name}` — {tool.description}")
        else:
            lines.append("- No tool registry was constructed for this vault.")
        lines += [
            "",
            "#### Important limits",
            "- The current agent does not autonomously browse the web, send email, call third-party SaaS, execute arbitrary shell commands, or edit/delete existing file contents.",
            "- The generated artifact is only as strong as retrieval coverage and source quality; citations identify retrieved evidence passages, not independent fact-checking.",
            "- Image OCR depends on image legibility. If Tesseract is missing, the configured Gemma model must support Ollama image input; otherwise the image remains indexed as a file with no text chunks.",
        ]
        return AgentResult(
            result_type="capabilities",
            content="\n".join(lines),
            data={
                "model": model,
                "llm_online": llm_online,
                "registered_tools": [tool.name for tool in registry_tools],
                "ocr": "tesseract-preferred-with-ollama-vision-fallback",
            },
        )

    def _handle_peek(self, vault: Vault, subfolder: str | None = None) -> AgentResult:
        """Inspect vault directory, strictly capped at 10-20 lines per file."""
        profiles = ShallowPeeker.inspect_directory(
            vault, subfolder=subfolder or "", max_lines_per_file=15, max_files=30
        )
        digest = ShallowPeeker.generate_directory_digest(profiles)

        return AgentResult(
            result_type="peek_results",
            content=digest,
            data={"profiles": profiles},
        )

    def _handle_chart(self, user_input: str, vault: Vault, subfolder: str | None = None) -> AgentResult:
        """Extract data from a CSV or Excel file and generate a high-quality chart."""
        lower = user_input.lower()

                                        
        csv_files = list(vault.root_path.rglob("*.csv")) + list(vault.root_path.rglob("*.xlsx"))
                                 
        csv_files = [
            f for f in csv_files
            if not any(part in (".git", ".venv", ".contextvault", vault.generated_dir.name) for part in f.parts)
            and vault.is_in_scope(f, subfolder)
        ]

        if not csv_files:
            return AgentResult(
                result_type="error",
                content="No CSV or Excel dataset files found in the vault to generate charts from.",
            )

                                          
        target_file = csv_files[0]
        for f in csv_files:
            if f.name.lower() in lower or f.stem.lower() in lower:
                target_file = f
                break

        rel_path = vault.relative_path(target_file)

                           
        chart_type = "bar"
        if "line" in lower or "trend" in lower:
            chart_type = "line"
        elif "scatter" in lower:
            chart_type = "scatter"
        elif "pie" in lower or "breakdown" in lower:
            chart_type = "pie"

        try:
            chart_info = ChartGenerator.generate_chart(
                vault=vault,
                relative_path=rel_path,
                chart_type=chart_type,
            )

            img_rel = chart_info["image_relative_path"]
            title = chart_info["title"]
            x_col = chart_info["x_column"]
            y_col = chart_info["y_column"]

            content = (
                f"### Visual Chart Generated: {title}\n"
                f"- **Data Source**: `{rel_path}`\n"
                f"- **Chart Type**: `{chart_type.upper()}` ({y_col} vs {x_col})\n"
                f"- **Saved Image**: `{img_rel}`\n\n"
                f"![{title}]({img_rel})"
            )

                                                                     
            if "pdf" in lower or "report" in lower:
                pdf_info = PDFCompiler.compile_pdf(
                    vault=vault,
                    title=f"Data Analysis Report: {title}",
                    content_markdown=f"Analysis of dataset `{rel_path}` showing {y_col} across {x_col}.\n\nGenerated with the configured local Ollama model.",
                    charts=[img_rel],
                )
                content += f"\n\n**Compiled PDF Artifact**: `{pdf_info['relative_path']}`"

            return AgentResult(
                result_type="generated_chart",
                content=content,
                data=chart_info,
            )
        except Exception as e:
            return AgentResult(
                result_type="error",
                content=f"Failed to generate chart from `{rel_path}`: {e}",
                errors=[str(e)],
            )

    def _handle_rag(self, query: str, vault: Vault, subfolder: str | None = None) -> AgentResult:
        """Handle factual / explanatory questions using filesystem-native retrieval."""
        if not self.rag_service:
            return AgentResult(
                result_type="error",
                content="Filesystem retrieval is unavailable for the current vault.",
            )

        response = self.rag_service.ask(query, vault.vault_id, subfolder=subfolder)
        return AgentResult(
            result_type="answer",
            content=response.answer,
            citations=response.sources,
            data={"confidence": response.confidence, "subfolder": subfolder},
        )

    def _handle_search(self, user_input: str, params: dict, vault: Vault, subfolder: str | None = None) -> AgentResult:
        """Search documents for keywords or semantic queries."""
        if not self.rag_service:
            return AgentResult(result_type="error", content="Search service unavailable.")

                              
        query = params.get("query")
        if not query or query == user_input:
            query = re.sub(r"^(?:search(?:\s+for)?|find|where(?:\s+is|\s+are)?|look\s+up)\s+", "", user_input, flags=re.IGNORECASE).strip()
            query = query.strip("\"'")

        results = self.rag_service.search(query, vault.vault_id, top_k=8, subfolder=subfolder)

        if not results:
            return AgentResult(
                result_type="search_results",
                content=f"No matching documents found in vault `{vault.display_name}` for query: **'{query}'**.",
                data={"query": query, "results": []},
            )

        lines = [f"### Search Results for '{query}':\n"]
        for i, r in enumerate(results, 1):
            score_bar = f"{r.score:.2f}"
            page_text = f" (page {r.page})" if r.page else ""
            lines.append(f"**{i}. [{r.filename}]({r.relative_path})** — Relevance: `{score_bar}`{page_text}")
            snippet = r.snippet.replace("\n", " ").strip()
            if len(snippet) > 160:
                snippet = snippet[:160] + "..."
            lines.append(f"> {snippet}\n")

        return AgentResult(
            result_type="search_results",
            content="\n".join(lines),
            data={"query": query, "results": results},
        )

    def _handle_duplicates(self, vault: Vault, subfolder: str | None = None) -> AgentResult:
        """Detect exact SHA-256 duplicate files and potential version revisions."""
        if not self.organisation_service:
            return AgentResult(result_type="error", content="Duplicate detection service unavailable.")

        exact, versions = self.organisation_service.detect_duplicates(subfolder=subfolder)

        lines = ["### Vault Duplicate & Revision Analysis\n"]

        if exact:
            lines.append(f"**Exact Duplicates Found ({len(exact)} groups, identical content):**")
            for group in exact:
                hash_preview = group.hash[:12] if group.hash else "unknown"
                lines.append(f"- **SHA-256: `{hash_preview}...`**")
                for f in group.files:
                    lines.append(f"  - `{f.relative_path}` ({f.size:,} bytes)")
            lines.append("")
        else:
            lines.append("No exact duplicate files detected (all distinct SHA-256 hashes).\n")

        if versions:
            lines.append(f"**Probable File Versions ({len(versions)} groups):**")
            for group in versions:
                lines.append(f"- _{group.reason}_:")
                for f in group.files:
                    lines.append(f"  - `{f.relative_path}`")
            lines.append("")
        else:
            lines.append("No suspicious version revisions detected.\n")

        lines.append("_Safety reminder: Context Vault never deletes files automatically._")

        return AgentResult(
            result_type="duplicates",
            content="\n".join(lines),
            data={"exact": exact, "versions": versions},
        )

    def _handle_organise(self, user_input: str, vault: Vault, subfolder: str | None = None) -> AgentResult:
        """Generate an organisation plan, leveraging shallow directory peeking."""
        if not self.organisation_service:
            return AgentResult(result_type="error", content="Organisation service unavailable.")

        lower = user_input.lower()
        strategy = "deterministic"
        primary = "file-family"
        custom_param = None

        if "divide by" in lower or "divide into" in lower or "split into" in lower or "categorize by" in lower:
            strategy = "semantic"
            primary = "custom"
            custom_param = user_input.strip()
        elif "extension" in lower or "type" in lower:
            primary = "file-type"
        elif "date" in lower or "year" in lower or "month" in lower:
            primary = "date-year"
        elif "size" in lower:
            primary = "size"
        elif "semantic" in lower or "subject" in lower or "topic" in lower or "course" in lower:
            strategy = "semantic"
            primary = "subject"

        rules = OrganisationRules(
            strategy=strategy,
            primary_grouping=primary,
            custom_parameter=custom_param,
            max_depth=2,
        )

        plan = self.organisation_service.preview(rules, subfolder=subfolder)

        lines = [
            f"### Proposed Organisation Plan",
            f"**Strategy**: `{strategy}` | **Grouping**: `{primary}`",
            f"- **Directories to create**: `{len(plan.directories_to_create)}`",
            f"- **Files to move**: `{len(plan.operations)}`",
            f"- **Files untouched**: `{len(plan.untouched_files)}`\n",
        ]

        if plan.directories_to_create:
            lines.append("**New Folders:**")
            for d in plan.directories_to_create:
                lines.append(f"- `[Folder] {d}`")
            lines.append("")

        if plan.operations:
            lines.append("**Sample Operations (Reversible):**")
            for op in plan.operations[:5]:
                lines.append(f"- `{op.source}` -> `{op.destination}`")
            if len(plan.operations) > 5:
                lines.append(f"- _...and {len(plan.operations) - 5} more files._")
            lines.append("")

        lines.append("> Use the **Organise** page or run `cvault organise` to inspect the full tree and apply with SHA-256 verification.")

        return AgentResult(
            result_type="organisation_plan",
            content="\n".join(lines),
            data={"plan": plan},
        )

    def _handle_generate(self, user_input: str, params: dict, vault: Vault, subfolder: str | None = None) -> AgentResult:
        """Generate learning materials (study guides, summaries, flashcards, etc.) and optional PDFs."""
        if not self.generation_service:
            return AgentResult(result_type="error", content="Generation service unavailable.")

        lower = user_input.lower()
        asset_type = "summary"
        if "study" in lower or "guide" in lower:
            asset_type = "study-guide"
        elif "flash" in lower or "card" in lower:
            asset_type = "flashcards"
        elif "quiz" in lower or "test" in lower:
            asset_type = "quiz"
        elif "revision" in lower or "notes" in lower:
            asset_type = "revision-notes"
        elif "timeline" in lower:
            asset_type = "timeline"
        elif "report" in lower:
            asset_type = "vault-report"

        topic = params.get("query")
        if not topic or topic == user_input:
            topic = re.sub(
                r"^(?:generate|create|make|write)(?:\s+a|\s+an)?\s+(?:study\s+guide|flashcards?|quiz|summary|revision\s+notes?|timeline|report|pdf)?(?:\s+(?:on|about|for))?\s*",
                "",
                user_input,
                flags=re.IGNORECASE,
            ).strip().strip("\"'")

                                 
        asset = self.generation_service.generate(
            asset_type=asset_type,
            topic=topic if topic else None,
            count=10 if asset_type in ("flashcards", "quiz") else None,
            subfolder=subfolder,
        )

        full_path = vault.root_path / asset.relative_path
        markdown_body = ""
        if full_path.exists():
            markdown_body = full_path.read_text(encoding="utf-8")

        preview = markdown_body[:600] + ("\n\n*(Content truncated in preview)*" if len(markdown_body) > 600 else "")

        content = (
            f"### Successfully Generated: {asset.title}\n"
            f"- **Markdown File**: `{asset.relative_path}`\n"
        )

                                            
        if "pdf" in lower or asset_type in ("study-guide", "vault-report"):
            try:
                pdf_res = PDFCompiler.compile_pdf(
                    vault=vault,
                    title=asset.title,
                    content_markdown=markdown_body,
                    output_filename=f"{asset.filename.replace('.md', '.pdf')}",
                )
                content += f"- **Compiled PDF**: `{pdf_res['relative_path']}`\n"
            except Exception as e:
                logger.warning(f"Could not compile PDF: {e}")

        content += f"\n---\n\n{preview}"

        return AgentResult(
            result_type="generated_file",
            content=content,
            data={"asset": asset},
        )

    def _handle_status(self, vault: Vault) -> AgentResult:
        """Provide detailed status of the active vault and models."""
        info = self.vault_service.get_vault_status(vault) if self.vault_service else {}
        config = self.services.get("config")
        model_name = config.ollama_model if config else "gemma4:e2b"

        text = (
            f"### Vault Status: `{vault.display_name}`\n"
            f"- **Path**: `{vault.root_path}`\n"
            f"- **Files Tracked**: `{info.get('file_count', 0)}`\n"
            f"- **Chunks Indexed**: `{info.get('chunk_count', 0)}`\n"
            f"- **Last Indexed**: `{info.get('last_indexed_at', 'Never')}`\n"
            f"- **Local LLM**: `{model_name}`\n"
            f"- **Ollama Connection**: `{'Connected' if (self.llm_client and self.llm_client.is_available()) else 'Offline'}`\n"
            "- **Retrieval Engine**: `Filesystem-Native Agentic Retrieval`"
        )

        return AgentResult(
            result_type="status",
            content=text,
            data=info,
        )
