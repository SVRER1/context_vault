"""Tool suite for Context Vault's local agent."""

from dataclasses import asdict

from contextvault.tools.base import ToolDefinition, ToolRegistry, ToolResult
from contextvault.tools.peeker import ShallowPeeker
from contextvault.tools.charts import ChartGenerator
from contextvault.parsers.image import ImageOCRParser
from contextvault.retrieval.filesystem_models import RetrievalRequest

__all__ = [
    "ToolDefinition",
    "ToolRegistry",
    "ToolResult",
    "ShallowPeeker",
    "ChartGenerator",
    "ImageOCRParser",
    "build_default_tool_registry",
]


def build_default_tool_registry(vault, services) -> ToolRegistry:
    """Build and register all deterministic tools for the active vault."""
    registry = ToolRegistry()

    def scoped_path(file_path, subfolder=""):
        vault.scope_root(subfolder)
        if not vault.is_in_scope(file_path, subfolder):
            raise ValueError(f"Path is outside the selected source scope: {file_path}")
        return vault.absolute_path(file_path)

    def scoped_directory(subfolder="", max_lines_per_file=15):
        vault.scope_root(subfolder)
        return ShallowPeeker.inspect_directory(
            vault, subfolder=subfolder, max_lines_per_file=max_lines_per_file
        )

                                                             
    registry.register(
        name="peek_directory",
        description="Inspect files in a folder, reading at most 10-20 lines per file to understand file contents without context overflow.",
        parameters={
            "subfolder": {"type": "string", "description": "Relative directory within the vault (default: root)"},
            "max_lines_per_file": {"type": "integer", "description": "Lines to sample per file, clamped to 10-20 (default: 15)"},
        },
        func=scoped_directory,
    )

                                   
    registry.register(
        name="peek_file",
        description="Read the first 10-20 lines from a specific file to identify its contents.",
        parameters={
            "file_path": {"type": "string", "description": "Relative path of the file to inspect"},
            "max_lines": {"type": "integer", "description": "Lines to sample, 10-20 (default: 15)"},
            "subfolder": {"type": "string", "description": "Selected source directory boundary"},
        },
        func=lambda file_path, max_lines=15, subfolder="": ShallowPeeker.peek_file(
            scoped_path(file_path, subfolder), max_lines=max_lines
        ),
    )

                        
    registry.register(
        name="inspect_dataset",
        description="Analyze columns, data types, and statistics of a CSV or Excel file in the vault.",
        parameters={
            "file_path": {"type": "string", "description": "Relative path to CSV or Excel spreadsheet"},
            "subfolder": {"type": "string", "description": "Selected source directory boundary"},
        },
        func=lambda file_path, subfolder="": ChartGenerator.inspect_dataset(vault, vault.relative_path(scoped_path(file_path, subfolder))),
    )

                       
    registry.register(
        name="generate_chart",
        description="Generate a visual chart (bar, line, scatter, pie) from CSV/Excel data and save as PNG image.",
        parameters={
            "file_path": {"type": "string", "description": "Relative path to CSV/XLSX file with data"},
            "chart_type": {"type": "string", "description": "bar, line, scatter, or pie (default: bar)"},
            "x_column": {"type": "string", "description": "Column name for X axis (labels / categories)"},
            "y_column": {"type": "string", "description": "Column name for Y axis (numeric values to plot)"},
            "title": {"type": "string", "description": "Chart title"},
            "output_filename": {"type": "string", "description": "Optional custom filename for saved PNG"},
            "subfolder": {"type": "string", "description": "Selected source directory boundary"},
        },
        func=lambda file_path, chart_type="bar", x_column=None, y_column=None, title=None, output_filename=None, subfolder="": ChartGenerator.generate_chart(
            vault, vault.relative_path(scoped_path(file_path, subfolder)), chart_type=chart_type, x_column=x_column, y_column=y_column, title=title, output_filename=output_filename
        ),
    )

                             
    from contextvault.generation.pdf_compiler import PDFCompiler
    registry.register(
        name="compile_pdf_artifact",
        description="Compile formatted text, data tables, and generated charts into a structured PDF document in Generated/.",
        parameters={
            "title": {"type": "string", "description": "Document title"},
            "content_markdown": {"type": "string", "description": "Document body in Markdown format"},
            "output_filename": {"type": "string", "description": "Optional PDF filename"},
            "charts": {"type": "array", "description": "Optional list of chart PNG relative paths to embed"},
        },
        func=lambda title, content_markdown, output_filename=None, charts=None: PDFCompiler.compile_pdf(
            vault, title=title, content_markdown=content_markdown, output_filename=output_filename, charts=charts
        ),
    )

                  
    registry.register(
        name="ocr_image",
        description=(
            "Extract searchable text from a JPG, PNG, GIF, BMP, TIFF, or WEBP image. "
            "Uses local Tesseract when available and the configured Ollama vision model as fallback."
        ),
        parameters={
            "file_path": {"type": "string", "description": "Relative image path inside the vault"},
            "subfolder": {"type": "string", "description": "Selected source directory boundary"},
        },
        func=lambda file_path, subfolder="": ImageOCRParser(
            ocr_client=services.get("llm_client")
        ).parse(scoped_path(file_path, subfolder), "ocr-tool")
        .model_dump(),
    )

                                               
    filesystem_service = services.get("filesystem_retrieval_service")
    if filesystem_service:
        registry.register(
            name="survey_scope",
            description="Survey the selected directory's paths, metadata, parser support, and cheap previews without reading complete files.",
            parameters={
                "subfolder": {"type": "string", "description": "Relative source directory; empty means entire vault"},
            },
            func=lambda subfolder="": [asdict(item) for item in filesystem_service.survey_service.survey(subfolder)],
        )
        registry.register(
            name="search_scope_text",
            description="Rank in-scope files using path, filename, lexical, metadata, and bounded preview signals without embeddings.",
            parameters={
                "query": {"type": "string", "description": "Question or search terms"},
                "subfolder": {"type": "string", "description": "Relative source directory"},
            },
            func=lambda query, subfolder="": [asdict(item) for item in filesystem_service.search(RetrievalRequest(
                query=query, vault_id=vault.vault_id, source_scope=subfolder, operation="search"
            ))],
        )
        registry.register(
            name="build_evidence",
            description="Construct bounded, source-attributed evidence Markdown and provenance for a query within the selected scope.",
            parameters={
                "query": {"type": "string", "description": "Question or artifact topic"},
                "subfolder": {"type": "string", "description": "Relative source directory"},
            },
            func=lambda query, subfolder="": asdict(filesystem_service.retrieve(RetrievalRequest(
                query=query, vault_id=vault.vault_id, source_scope=subfolder, operation="ask"
            ))),
        )

                              
    rag_service = services.get("rag_service")
    if rag_service:
        registry.register(
            name="rag_search",
            description="Search indexed documents using hybrid semantic and lexical retrieval.",
            parameters={
                "query": {"type": "string", "description": "Search query or topic to find relevant passages for"},
            },
            func=lambda query: rag_service.search(query, vault.vault_id, top_k=8),
        )

                           
    org_service = services.get("organisation_service")
    if org_service:
        registry.register(
            name="detect_duplicates",
            description="Find exact SHA-256 duplicate files and potential version revisions across the vault.",
            parameters={"subfolder": {"type": "string", "description": "Relative source directory"}},
            func=lambda subfolder="": org_service.detect_duplicates(subfolder=subfolder),
        )

    return registry
