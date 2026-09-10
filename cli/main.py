"""Context Vault CLI - Typer + Rich command-line interface."""

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.tree import Tree

from contextvault.core.config import get_config
from contextvault.services.service_container import ServiceContainer

app = typer.Typer(
    name="cvault",
    help="Context Vault - Local-first agentic file intelligence workspace",
    no_args_is_help=True,
)
console = Console()

                       
_container: ServiceContainer | None = None


def get_container() -> ServiceContainer:
    """Get or create the global service container."""
    global _container
    if _container is None:
        _container = ServiceContainer()
    return _container


def _state_file() -> Path:
    """Path to the active vault state file."""
    config = get_config()
    return config.app_data_path / "active_vault.json"


def _get_active_vault_path() -> Path | None:
    """Read the last active vault path from state file."""
    sf = _state_file()
    if sf.exists():
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            p = data.get("active_vault_path")
            if p:
                return Path(p)
        except Exception:
            pass
    return None


def _set_active_vault_path(path: Path) -> None:
    """Save the active vault path to state file."""
    sf = _state_file()
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(
        json.dumps({"active_vault_path": str(path.resolve())}),
        encoding="utf-8",
    )


def _require_active_vault():
    """Open the active vault or exit with error."""
    vault_path = _get_active_vault_path()
    if not vault_path:
        console.print(
            Panel(
                "[red]No active vault. Use 'cvault open PATH' to open a vault first.[/red]",
                title="Error",
            )
        )
        raise typer.Exit(1)
    if not vault_path.exists():
        console.print(
            Panel(f"[red]Active vault path no longer exists: {vault_path}[/red]", title="Error")
        )
        raise typer.Exit(1)

    container = get_container()
    try:
        vault = container.open_vault(vault_path)
        return container, vault
    except Exception as e:
        console.print(Panel(f"[red]Error opening vault: {e}[/red]", title="Error"))
        raise typer.Exit(1)


def _resolve_scope(vault, scope: str | None) -> str | None:
    """Validate and normalize an optional directory scope within the vault."""
    if not scope or not scope.strip("/\\"):
        return None
    try:
        return vault.scope_relative_path(scope)
    except Exception as e:
        console.print(Panel(f"[red]Invalid directory scope: {e}[/red]", title="Error"))
        raise typer.Exit(1)


                                                                  

@app.command("open")
def open_vault(path: str = typer.Argument(..., help="Path to the vault directory")):
    """Open a folder as the active vault and run initial scan."""
    vault_path = Path(path).resolve()
    if not vault_path.exists() or not vault_path.is_dir():
        console.print(Panel(f"[red]Not a valid directory: {vault_path}[/red]", title="Error"))
        raise typer.Exit(1)

    container = get_container()
    with console.status("Opening vault..."):
        try:
            vault = container.open_vault(vault_path)
        except Exception as e:
            console.print(Panel(f"[red]Error: {e}[/red]", title="Error"))
            raise typer.Exit(1)

                    
    try:
        files = container.vault_service.scan_vault(vault, container.vault_db)
        _set_active_vault_path(vault_path)
    except Exception as e:
        console.print(f"[yellow]Scan warning: {e}[/yellow]")
        files = []
        _set_active_vault_path(vault_path)

    supported_exts = {
        ".txt", ".md", ".rst", ".log", ".py", ".java", ".c", ".cpp", ".h",
        ".hpp", ".cs", ".rs", ".js", ".ts", ".html", ".css", ".json", ".yaml",
        ".yml", ".toml", ".xml", ".sql", ".sh", ".ps1", ".pdf", ".docx",
        ".pptx", ".csv", ".xlsx",
    }
    supported = sum(1 for f in files if f.extension.lower() in supported_exts)
    unsupported = len(files) - supported

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Active Vault", vault.display_name)
    table.add_row("Path", str(vault.root_path))
    table.add_row("Files", str(len(files)))
    table.add_row("Supported", str(supported))
    table.add_row("Unsupported", str(unsupported))
    console.print(Panel(table, title="[green]Vault Opened Successfully[/green]", expand=False))


@app.command("vaults")
def list_vaults():
    """List all registered vaults."""
    container = get_container()
    vaults = container.vault_service.list_vaults()
    active_path = _get_active_vault_path()

    table = Table(title="Registered Vaults")
    table.add_column("Active", justify="center")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="yellow")
    table.add_column("Files", style="blue", justify="right")
    table.add_column("Last Opened", style="magenta")

    for v in vaults:
        active = "*" if active_path and str(Path(v.absolute_path).resolve()) == str(active_path.resolve()) else ""
        table.add_row(
            active,
            v.display_name,
            v.absolute_path,
            str(v.file_count),
            v.last_opened_at.strftime("%Y-%m-%d %H:%M") if v.last_opened_at else "-",
        )
    console.print(table)


@app.command("status")
def status():
    """Show status of the active vault."""
    container, vault = _require_active_vault()
    info = container.vault_service.get_vault_status(vault)
    config = container.config

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Active Vault", info.get("display_name", vault.display_name))
    table.add_row("Path", info.get("path", str(vault.root_path)))
    table.add_row("File Count", str(info.get("file_count", 0)))
    table.add_row("Chunk Count", str(info.get("chunk_count", 0)))
    table.add_row("Last Indexed", str(info.get("last_indexed_at", "Never")))
    table.add_row("LLM", f"{config.ollama_model} @ {config.ollama_base_url}")
    table.add_row("Retrieval", "Filesystem-native, directory-scoped evidence")
    table.add_row("LLM Available", "Yes" if container.has_llm else "No (fallback mode)")
    console.print(Panel(table, title="Vault Status", expand=False))


@app.command("scan")
def scan():
    """Scan the active vault for files."""
    container, vault = _require_active_vault()

    with console.status("Scanning..."):
        files = container.vault_service.scan_vault(vault, container.vault_db)

                   
    type_counts: dict[str, int] = {}
    for f in files:
        family = f.mime_family or "other"
        type_counts[family] = type_counts.get(family, 0) + 1

    table = Table(title=f"Scan Complete - {len(files)} files")
    table.add_column("Type", style="cyan")
    table.add_column("Count", style="green", justify="right")
    for t, c in sorted(type_counts.items()):
        table.add_row(t.capitalize(), str(c))
    console.print(table)


@app.command("index")
def index():
    """Run an optional parse/cache pass; retrieval does not require indexing."""
    container, vault = _require_active_vault()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
    ) as progress:
        task_id = progress.add_task("Indexing...", total=100)

        def on_progress(current, total, msg=""):
            if total > 0:
                progress.update(task_id, completed=int(current / total * 100), description=msg or "Indexing...")

        try:
            stats = container.vault_service.index_vault(
                vault,
                container.vault_db,
                progress_callback=on_progress,
                ocr_client=container.llm_client,
            )
            progress.update(task_id, completed=100, description="Done!")
        except Exception as e:
            console.print(Panel(f"[red]Indexing failed: {e}[/red]", title="Error"))
            raise typer.Exit(1)

    table = Table(show_header=False, box=None)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    for k, v in stats.items():
        table.add_row(k.replace("_", " ").title(), str(v))
    console.print(Panel(table, title="[green]Indexing Complete[/green]", expand=False))


@app.command("ask")
def ask(
    question: str = typer.Argument(..., help="Question to ask the vault"),
    scope: str | None = typer.Option(None, "--scope", help="Relative directory to use as the source of truth"),
):
    """Ask a question answered using RAG from vault files."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)

    with console.status("Thinking..."):
        try:
            response = container.rag_service.ask(question, vault.vault_id, subfolder=scope)
        except Exception as e:
            console.print(Panel(f"[red]{e}[/red]", title="Error"))
            raise typer.Exit(1)

    console.print(Panel(response.answer, title="Answer", border_style="green"))

    if response.sources:
        console.print("\n[bold]Sources:[/bold]")
        for i, src in enumerate(response.sources, 1):
            page = f" · p.{src.page}" if src.page else ""
            section = f" · {src.section}" if src.section else ""
            console.print(f"  [{i}] [cyan]{src.file_path}{page}{section}[/cyan]")


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query"),
    scope: str | None = typer.Option(None, "--scope", help="Relative directory to search"),
):
    """Hybrid search across the vault."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)

    with console.status("Searching..."):
        try:
            results = container.rag_service.search(query, vault.vault_id, subfolder=scope)
        except Exception as e:
            console.print(Panel(f"[red]Search failed: {e}[/red]", title="Error"))
            raise typer.Exit(1)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Results for '{query}'")
    table.add_column("File", style="cyan")
    table.add_column("Path", style="blue")
    table.add_column("Snippet", style="white", max_width=60)
    table.add_column("Score", style="yellow", justify="right")

    for r in results[:10]:
        snippet = r.snippet[:100] + "..." if len(r.snippet) > 100 else r.snippet
        table.add_row(r.filename, r.relative_path, snippet, f"{r.score:.2f}")
    console.print(table)


@app.command("duplicates")
def duplicates(
    scope: str | None = typer.Option(None, "--scope", help="Relative directory to inspect"),
):
    """Detect exact duplicates and probable file versions."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)

    with console.status("Detecting duplicates..."):
        try:
            exact, versions = container.organisation_service.detect_duplicates(scope)
        except Exception as e:
            console.print(Panel(f"[red]{e}[/red]", title="Error"))
            raise typer.Exit(1)

    if exact:
        console.print(f"\n[bold red]Exact Duplicates ({len(exact)} groups):[/bold red]")
        for group in exact:
            h_str = group.hash[:16] + "..." if group.hash else ""
            console.print(f"  [yellow]Hash: {h_str}[/yellow]")
            for f in group.files:
                console.print(f"    * {f.relative_path}  ({f.size:,} bytes)")
    else:
        console.print("[green]No exact duplicates found.[/green]")

    if versions:
        console.print(f"\n[bold yellow]Possible Versions ({len(versions)} groups):[/bold yellow]")
        for group in versions:
            console.print(f"  [dim]{group.reason}[/dim]")
            for f in group.files:
                console.print(f"    * {f.relative_path}")
    else:
        console.print("[green]No probable versions detected.[/green]")


@app.command("organise")
def organise(
    strategy: str = typer.Option("type", help="Strategy: type, date, size, family, semantic, hybrid"),
    primary: str = typer.Option("file-type", help="Primary grouping"),
    secondary: str = typer.Option("none", help="Secondary grouping"),
    depth: int = typer.Option(2, help="Max hierarchy depth (1-4)"),
    preview: bool = typer.Option(True, help="Show preview before applying"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    scope: str | None = typer.Option(None, "--scope", help="Relative directory to organise"),
):
    """Organise vault files by rules."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)

    strategy_map = {"type": "deterministic", "date": "deterministic", "size": "deterministic", "family": "deterministic"}
    actual_strategy = strategy_map.get(strategy, strategy)

    if strategy in ("type", "date", "size", "family"):
        primary = f"file-{strategy}" if strategy != "date" else "date-year"

    from contextvault.organisation.rules import OrganisationRules
    rules = OrganisationRules(
        strategy=actual_strategy,
        primary_grouping=primary,
        secondary_grouping=secondary if secondary != "none" else None,
        max_depth=depth,
    )

    with console.status("Generating organisation plan..."):
        try:
            plan = container.organisation_service.preview(rules, subfolder=scope)
        except Exception as e:
            console.print(Panel(f"[red]{e}[/red]", title="Error"))
            raise typer.Exit(1)

                     
    if plan.directories_to_create:
        tree = Tree(f"[Folder] {vault.display_name}")
        for d in plan.directories_to_create:
            tree.add(f"[Folder] [cyan]{d}[/cyan] (new)")
        console.print(tree)

    console.print(f"\nDirectories to create: [green]{len(plan.directories_to_create)}[/green]")
    console.print(f"Files to move: [green]{len(plan.operations)}[/green]")
    console.print(f"Files untouched: [yellow]{len(plan.untouched_files)}[/yellow]")
    if plan.warnings:
        for w in plan.warnings:
            console.print(f"[yellow]! {w}[/yellow]")

    if not plan.operations:
        console.print("[yellow]No operations to perform.[/yellow]")
        return

    if not yes:
        if not typer.confirm("Apply this organisation plan?", default=False):
            console.print("Cancelled.")
            return

    with console.status("Applying with hash verification..."):
        try:
            records = container.organisation_service.apply(plan)
            console.print(Panel(f"[green]Successfully applied {len(records)} operations with hash verification.[/green]"))
        except Exception as e:
            console.print(Panel(f"[red]Apply failed: {e}[/red]", title="Error"))
            raise typer.Exit(1)


@app.command("peek")
def peek(
    subfolder: str = typer.Argument("", help="Relative subfolder to peek (default: vault root)"),
    lines: int = typer.Option(15, help="Number of lines to read per file (clamped to 10-20)"),
):
    """Shallow inspection of files in vault directory (10-20 lines per file)."""
    container, vault = _require_active_vault()
    subfolder = _resolve_scope(vault, subfolder)
    from contextvault.tools.peeker import ShallowPeeker

    with console.status("Peeking directory..."):
        profiles = ShallowPeeker.inspect_directory(vault, subfolder=subfolder, max_lines_per_file=lines)
        digest = ShallowPeeker.generate_directory_digest(profiles)
    console.print(digest)


@app.command("chart")
def chart(
    file_path: str = typer.Argument(..., help="Relative path to CSV or Excel file"),
    chart_type: str = typer.Option("bar", "--type", "--chart-type", help="Chart type: bar, line, scatter, pie"),
    x: str = typer.Option(None, "--x", help="X-axis column"),
    y: str = typer.Option(None, "--y", help="Y-axis column"),
    title: str = typer.Option(None, help="Chart title"),
    scope: str | None = typer.Option(None, "--scope", help="Relative directory containing the dataset"),
):
    """Generate a visual chart PNG from CSV or Excel data."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)
    if scope and not vault.is_in_scope(file_path, scope):
        console.print(Panel("[red]The dataset is outside the selected directory scope.[/red]", title="Error"))
        raise typer.Exit(1)
    from contextvault.tools.charts import ChartGenerator

    with console.status(f"Generating {chart_type} chart..."):
        try:
            info = ChartGenerator.generate_chart(
                vault, relative_path=file_path, chart_type=chart_type, x_column=x, y_column=y, title=title
            )
            console.print(Panel(
                f"[green]Chart generated successfully![/green]\n"
                f"Title: {info['title']}\n"
                f"Image: {info['image_relative_path']}\n"
                f"Data Points: {info['points_count']}",
                title="Chart Generated",
            ))
        except Exception as e:
            console.print(Panel(f"[red]Chart generation failed: {e}[/red]", title="Error"))
            raise typer.Exit(1)


@app.command("generate")
def generate(
    asset_type: str = typer.Argument(
        ..., help="Asset type: summary, study-guide, revision-notes, flashcards, quiz, timeline, vault-report"
    ),
    topic: str = typer.Option(None, help="Topic to focus on"),
    count: int = typer.Option(10, help="Number of items (flashcards/quiz)"),
    filename: str = typer.Option(None, help="Output filename"),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="Also compile into a styled PDF document"),
    scope: str | None = typer.Option(None, "--scope", help="Relative directory to use as the source of truth"),
):
    """Generate a new knowledge asset from vault content."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)

    with console.status(f"Generating {asset_type}..."):
        try:
            asset = container.generation_service.generate(
                asset_type=asset_type,
                topic=topic,
                count=count,
                filename=filename,
                subfolder=scope,
            )
        except Exception as e:
            console.print(Panel(f"[red]{e}[/red]", title="Error"))
            raise typer.Exit(1)

    output_info = (
        f"[green]Generated: {asset.title}[/green]\n"
        f"Markdown: {asset.relative_path}\n"
    )

    if pdf:
        try:
            from contextvault.generation.pdf_compiler import PDFCompiler
            full_path = vault.root_path / asset.relative_path
            md_body = full_path.read_text(encoding="utf-8") if full_path.exists() else ""
            pdf_res = PDFCompiler.compile_pdf(
                vault=vault,
                title=asset.title,
                content_markdown=md_body,
                output_filename=asset.filename.replace(".md", ".pdf"),
            )
            output_info += f"PDF Document: {pdf_res['relative_path']}\n"
        except Exception as e:
            output_info += f"[yellow]PDF compilation note: {e}[/yellow]\n"

    output_info += f"Folder: {vault.root_path / 'Generated'}"
    console.print(Panel(output_info, title="Generation Complete"))


@app.command("audit")
def audit():
    """Show recent file operations audit log."""
    container, vault = _require_active_vault()

    try:
        ops = container.audit_service.get_operations(vault.vault_id)
    except Exception as e:
        console.print(Panel(f"[red]{e}[/red]", title="Error"))
        raise typer.Exit(1)

    if not ops:
        console.print("[yellow]No operations recorded yet.[/yellow]")
        return

    table = Table(title="Audit Log")
    table.add_column("Time", style="cyan")
    table.add_column("Operation", style="magenta")
    table.add_column("Source", style="blue")
    table.add_column("Destination", style="green")
    table.add_column("Status", style="yellow")

    for op in ops[:20]:
        table.add_row(
            op.timestamp.strftime("%Y-%m-%d %H:%M"),
            op.operation_type,
            op.source_path,
            op.destination_path or "-",
            op.status,
        )
    console.print(table)


@app.command("undo")
def undo(
    operation_id: str = typer.Argument(None, help="Operation ID to undo (omit for last batch)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Undo the last organisation batch or a specific operation."""
    container, vault = _require_active_vault()

    if not yes:
        if not typer.confirm("Are you sure you want to undo?", default=False):
            console.print("Cancelled.")
            return

    try:
        if operation_id:
            result = container.audit_service.undo_operation(operation_id, vault)
            console.print(f"[green]Undid operation {operation_id}[/green]")
        else:
            ops = container.audit_service.get_undoable_operations(vault.vault_id)
            if not ops:
                console.print("[yellow]No undoable operations found.[/yellow]")
                return
            last_batch = ops[0].batch_id
            if last_batch:
                results = container.audit_service.undo_batch(last_batch, vault)
                console.print(f"[green]Undid {len(results)} operations from last batch.[/green]")
            else:
                result = container.audit_service.undo_operation(ops[0].operation_id, vault)
                console.print(f"[green]Undid last operation.[/green]")
    except Exception as e:
        console.print(Panel(f"[red]Undo failed: {e}[/red]", title="Error"))
        raise typer.Exit(1)


@app.command("chat")
def chat():
    """Interactive conversation mode."""
    container, vault = _require_active_vault()

    console.print(Panel(
        f"[bold green]Context Vault Chat[/bold green]\n"
        f"Vault: {vault.display_name}\n"
        f"Type 'exit' or 'quit' to leave.",
        expand=False,
    ))

    while True:
        try:
            user_input = console.input("[bold blue]> [/bold blue]").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        try:
            result = container.orchestrator.handle_query(user_input, vault)
            console.print(f"\n{result.content}\n")
            if result.citations:
                console.print("[dim]Sources:[/dim]")
                for i, src in enumerate(result.citations, 1):
                    page = f" · p.{src.page}" if src.page else ""
                    console.print(f"  [{i}] [cyan]{src.file_path}{page}[/cyan]")
                console.print()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]\n")


@app.command("desktop")
def launch_desktop():
    """Launch the Context Vault desktop application."""
    try:
        from desktop.main import main as desktop_main
        desktop_main()
    except ImportError as e:
        console.print(Panel(f"[red]Could not launch desktop: {e}[/red]", title="Error"))
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
