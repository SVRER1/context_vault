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
from contextvault.query.errors import QueryError
from contextvault.query.parser import parse_query
from contextvault.retrieval.search_models import SearchRequest
from contextvault.filesystem.plan_models import RouteEntry, RouteSpec, route_from_data
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


def _render_search_response(response, title: str) -> None:
    for diagnostic in response.diagnostics:
        console.print(f"[yellow]{diagnostic}[/yellow]")
    if response.unknown_ids:
        console.print(f"[yellow]{len(response.unknown_ids)} file(s) have unknown/incomplete query results.[/yellow]")
    if not response.hits:
        console.print("[yellow]No results found.[/yellow]")
        return
    table = Table(title=title)
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("File", style="cyan")
    table.add_column("Path", style="blue")
    table.add_column("Snippet", style="white", max_width=60)
    table.add_column("Score", style="yellow", justify="right")
    table.add_column("Location", style="magenta")
    for hit in response.hits:
        passage = hit.passages[0] if hit.passages else None
        snippet = passage.snippet if passage else ""
        if len(snippet) > 100:
            snippet = snippet[:100] + "..."
        location = ""
        if passage:
            location = passage.heading or passage.section or ""
            if passage.page is not None:
                location = f"p. {passage.page}" + (f" · {location}" if location else "")
            elif passage.line_start is not None:
                location = f"lines {passage.line_start}-{passage.line_end}" + (f" · {location}" if location else "")
        table.add_row(hit.file_id[:12], hit.filename, hit.relative_path, snippet, f"{hit.score:.3f}", location)
    console.print(table)


def _render_operation_plan(plan) -> None:
    console.print(f"\nPlan ID: [cyan]{plan.plan_id}[/cyan]")
    console.print(f"Plan digest: [dim]{plan.digest}[/dim]")
    console.print(f"Files selected: [green]{len(plan.items)}[/green]")
    console.print(f"Conflicts: [red]{len(plan.conflicts)}[/red]")
    console.print(f"Skipped / review: [yellow]{len(plan.skips)}[/yellow]")
    for item in plan.items:
        console.print(f"  {item.action}: {item.source} -> {item.destination}")
    for issue in plan.conflicts:
        console.print(f"[red]Conflict: {issue.path or issue.file_id}: {issue.message}[/red]")
    for issue in (*plan.skips, *plan.warnings):
        console.print(f"[yellow]{issue.code}: {issue.path or ''} {issue.message}[/yellow]")


def _preview_route(query: str, into: str, *, action: str, scope: str | None):
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)
    try:
        rule = parse_query(query)
        plan = container.plan_service.preview_route(RouteSpec(
            entries=(RouteEntry(rule, into, action),), fallback="keep"
        ), scope=scope)
    except QueryError as exc:
        console.print(Panel(exc.render(query), title="Invalid query"))
        raise typer.Exit(2)
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Route preview failed"))
        raise typer.Exit(1)
    _render_operation_plan(plan)
    console.print("Dry run complete. No files changed. Commit with `cvault apply PLAN_ID`.")
    return plan


                                                                  

@app.command("open")
def open_vault(path: str = typer.Argument(..., help="Path to the vault directory")):
    """Open a folder as the active vault."""
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

    _set_active_vault_path(vault_path)
    info = container.vault_service.get_vault_status(vault)

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Active Vault", vault.display_name)
    table.add_row("Path", str(vault.root_path))
    table.add_row("Indexed files", str(info.get("file_count", 0)))
    table.add_row("Index status", "Current index (run `cvault scan` to reconcile)")
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

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Active Vault", info.get("display_name", vault.display_name))
    table.add_row("Path", info.get("path", str(vault.root_path)))
    table.add_row("File Count", str(info.get("file_count", 0)))
    table.add_row("Chunk Count", str(info.get("chunk_count", 0)))
    table.add_row("Last Indexed", str(info.get("last_indexed_at", "Never")))
    table.add_row("Retrieval", "SQLite FTS5/BM25 with deterministic rules")
    table.add_row("Optional synthesis", "Provider availability checked only when requested")
    console.print(Panel(table, title="Vault Status", expand=False))


@app.command("scan")
def scan():
    """Scan the active vault for files."""
    container, vault = _require_active_vault()

    with console.status("Scanning..."):
        stats = container.index_service.reconcile()
        files = container.vault_db.fetch_all(
            "SELECT * FROM files WHERE vault_id=? ORDER BY relative_path", (vault.vault_id,)
        )

                   
    type_counts: dict[str, int] = {}
    for f in files:
        family = f.get("mime_family") or "other"
        type_counts[family] = type_counts.get(family, 0) + 1

    table = Table(title=f"Scan Complete - {len(files)} files")
    table.add_column("Type", style="cyan")
    table.add_column("Count", style="green", justify="right")
    for t, c in sorted(type_counts.items()):
        table.add_row(t.capitalize(), str(c))
    console.print(table)


@app.command("index")
def index():
    """Reconcile the content index and report extraction statistics."""
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
            stats = container.index_service.reconcile(progress_callback=on_progress)
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
    synthesize: bool = typer.Option(False, "--synthesize", help="Generate an answer from deterministic retrieved evidence"),
):
    """Retrieve evidence by default; optionally generate a synthesized answer."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)

    with console.status("Thinking..."):
        try:
            response = (container.rag_service.synthesize if synthesize else container.rag_service.ask)(
                question, vault.vault_id, subfolder=scope
            )
        except Exception as e:
            console.print(Panel(f"[red]{e}[/red]", title="Error"))
            raise typer.Exit(1)

    console.print(Panel(response.answer, title="Synthesized answer" if synthesize else "Retrieved evidence", border_style="green"))

    if response.sources:
        console.print("\n[bold]Sources:[/bold]")
        for i, src in enumerate(response.sources, 1):
            page = f" · p.{src.page}" if src.page else ""
            section = f" · {src.section}" if src.section else ""
            console.print(f"  [{i}] [cyan]{src.file_path}{page}{section}[/cyan]")


@app.command("search")
def search(
    query: str | None = typer.Argument(None, help="Plain-text search query"),
    scope: str | None = typer.Option(None, "--scope", help="Relative directory to search"),
    where: str | None = typer.Option(None, "--where", help="Structured Boolean file rule"),
    limit: int = typer.Option(20, "--limit", min=1, max=1000, help="Maximum ranked files to show"),
):
    """Search indexed content or select files with a structured rule."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)
    if not query and not where:
        console.print(Panel("Provide a search query or --where expression.", title="Error"))
        raise typer.Exit(2)

    try:
        rule = parse_query(where) if where else None
    except QueryError as e:
        console.print(Panel(e.render(where or ""), title="Invalid query"))
        raise typer.Exit(2)

    with console.status("Searching..."):
        try:
            response = container.search_service.search(SearchRequest(
                vault_id=vault.vault_id,
                query=query,
                rule=rule,
                source_scope=scope,
                limit=limit,
            ))
        except Exception as e:
            console.print(Panel(f"[red]Search failed: {e}[/red]", title="Error"))
            raise typer.Exit(1)

    title = f"Results for '{query}'" if query else "Files matching rule"
    _render_search_response(response, title)


@app.command("query")
def query_command(
    expression: str = typer.Argument(..., help="Boolean rule expression, e.g. type:pdf AND content:\"vector database\""),
    scope: str | None = typer.Option(None, "--scope", help="Relative directory to search"),
    limit: int = typer.Option(20, "--limit", min=1, max=1000),
):
    """Select and rank files using the deterministic query language."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)
    try:
        rule = parse_query(expression)
    except QueryError as exc:
        console.print(Panel(exc.render(expression), title="Invalid query"))
        raise typer.Exit(2)
    try:
        response = container.search_service.search(SearchRequest(
            vault_id=vault.vault_id, rule=rule, source_scope=scope, limit=limit
        ))
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Query failed"))
        raise typer.Exit(1)
    _render_search_response(response, f"Files matching {expression}")


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
    preview: bool = typer.Option(True, "--preview/--commit", help="Preview without changing files (default); --commit applies after review"),
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
            plan = container.organisation_service.preview_plan(rules, subfolder=scope)
        except Exception as e:
            console.print(Panel(f"[red]{e}[/red]", title="Error"))
            raise typer.Exit(1)

    _render_operation_plan(plan)

    if not plan.items:
        console.print("[yellow]No operations to perform.[/yellow]")
        return

    if preview:
        console.print("[cyan]Dry run complete. No files changed. Commit this reviewed plan with `cvault apply PLAN_ID`.[/cyan]")
        return

    if plan.conflicts:
        console.print("[red]Plan has conflicts. Resolve them and create a new preview before applying.[/red]")
        raise typer.Exit(2)

    if not yes:
        if not typer.confirm("Apply this organisation plan?", default=False):
            console.print("Cancelled.")
            return

    with console.status("Applying with hash verification..."):
        try:
            result = container.organisation_service.commit_plan(plan.plan_id, plan.digest, approved=True)
            if result.status != "committed":
                raise RuntimeError(f"Batch {result.batch_id} ended in {result.status}: {result.error or ''}")
            console.print(Panel(f"[green]Successfully applied {len(result.completed)} operations. Batch: {result.batch_id}[/green]"))
        except Exception as e:
            console.print(Panel(f"[red]Apply failed: {e}[/red]", title="Error"))
            raise typer.Exit(1)


@app.command("move")
def move_command(
    where: str = typer.Option(..., "--where", help="Structured rule selecting source files"),
    into: str = typer.Option(..., "--into", help="Vault-relative destination directory"),
    scope: str | None = typer.Option(None, "--scope", help="Source directory boundary"),
):
    """Preview a rule-selected move; commit later with `cvault apply PLAN_ID`."""
    _preview_route(where, into, action="move", scope=scope)


@app.command("copy")
def copy_command(
    where: str = typer.Option(..., "--where", help="Structured rule selecting source files"),
    into: str = typer.Option(..., "--into", help="Vault-relative destination directory"),
    scope: str | None = typer.Option(None, "--scope", help="Source directory boundary"),
):
    """Preview a rule-selected copy; commit later with `cvault apply PLAN_ID`."""
    _preview_route(where, into, action="copy", scope=scope)


@app.command("route")
def route_command(
    where: str | None = typer.Option(None, "--where", help="Rule for one ordered route entry"),
    into: str | None = typer.Option(None, "--into", help="Destination for the --where rule"),
    rules_file: Path | None = typer.Option(None, "--rules-file", exists=True, readable=True, help="JSON RouteSpec with ordered entries"),
    fallback: str = typer.Option("review", help="Unmatched files: keep or review"),
    group_by: str | None = typer.Option(None, "--group-by", help="Deterministic subfolder key"),
    scope: str | None = typer.Option(None, "--scope", help="Source directory boundary"),
):
    """Preview ordered deterministic routes from a rule or RouteSpec JSON file."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)
    try:
        if rules_file:
            if where or into:
                raise ValueError("Use either --rules-file or --where/--into, not both.")
            route = route_from_data(json.loads(rules_file.read_text(encoding="utf-8")))
        else:
            if not where or not into:
                raise ValueError("Provide both --where and --into, or use --rules-file.")
            route = RouteSpec((RouteEntry(parse_query(where), into),), fallback=fallback, group_by=group_by)
        plan = container.plan_service.preview_route(route, scope=scope)
    except QueryError as exc:
        source = where or str(rules_file or "")
        console.print(Panel(exc.render(source), title="Invalid route rule"))
        raise typer.Exit(2)
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Route preview failed"))
        raise typer.Exit(1)
    _render_operation_plan(plan)
    console.print("Dry run complete. No files changed. Commit with `cvault apply PLAN_ID`.")


@app.command("rename")
def rename_command(
    source: str = typer.Argument(..., help="Vault-relative source path"),
    new_name: str = typer.Argument(..., help="New basename only"),
    scope: str | None = typer.Option(None, "--scope", help="Source directory boundary"),
):
    """Preview a safe rename, including case-only changes on Windows."""
    container, vault = _require_active_vault()
    scope = _resolve_scope(vault, scope)
    try:
        plan = container.plan_service.preview_rename(source, new_name, scope=scope)
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Rename preview failed"))
        raise typer.Exit(1)
    _render_operation_plan(plan)
    console.print("Dry run complete. No files changed. Commit with `cvault apply PLAN_ID`.")


@app.command("apply")
def apply_plan(
    plan_id: str = typer.Argument(..., help="Persisted operation plan ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Commit the reviewed plan without another prompt"),
):
    """Review and explicitly commit an immutable persisted plan by ID."""
    container, _vault = _require_active_vault()
    try:
        plan = container.plan_service.get_plan(plan_id)
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Plan unavailable"))
        raise typer.Exit(2)
    _render_operation_plan(plan)
    if plan.conflicts:
        console.print("[red]Conflicts block commit. Create a corrected preview.[/red]")
        raise typer.Exit(2)
    if not plan.items:
        console.print("[yellow]Plan has no operations.[/yellow]")
        return
    if not yes and not typer.confirm(f"Commit persisted plan {plan.plan_id}?", default=False):
        console.print("Cancelled. No files changed.")
        return
    result = container.execution_service.commit(plan.plan_id, plan.digest, approved=True)
    if result.status != "committed":
        console.print(Panel(
            f"Batch {result.batch_id} stopped in {result.status}: {result.error or ''}",
            title="Recovery required",
        ))
        raise typer.Exit(3)
    console.print(f"[green]Committed {len(result.completed)} operations. Batch: {result.batch_id}[/green]")


tag_app = typer.Typer(no_args_is_help=True, help="Maintain deterministic per-file labels")
app.add_typer(tag_app, name="tag")


@tag_app.command("add")
def add_tag(target: str = typer.Argument(..., help="File ID or vault-relative path"), tag: str = typer.Argument(...)):
    """Add a label without changing the file bytes."""
    container, _vault = _require_active_vault()
    try:
        tags = container.tag_service.add(target, tag)
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Could not add tag"))
        raise typer.Exit(1)
    console.print(f"Tags: {', '.join(tags)}")


@tag_app.command("remove")
def remove_tag(target: str = typer.Argument(..., help="File ID or vault-relative path"), tag: str = typer.Argument(...)):
    """Remove a label without changing the file bytes."""
    container, _vault = _require_active_vault()
    try:
        tags = container.tag_service.remove(target, tag)
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Could not remove tag"))
        raise typer.Exit(1)
    console.print(f"Tags: {', '.join(tags) if tags else '(none)'}")


@tag_app.command("list")
def list_tags(target: str = typer.Argument(..., help="File ID or vault-relative path")):
    """List a file's stored labels."""
    container, _vault = _require_active_vault()
    try:
        tags = container.tag_service.list(target)
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Could not list tags"))
        raise typer.Exit(1)
    console.print(", ".join(tags) if tags else "(no tags)")


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
    else:
        table = Table(title="Audit Log")
        table.add_column("Time", style="cyan")
        table.add_column("Operation", style="magenta")
        table.add_column("Source", style="blue")
        table.add_column("Destination", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Provenance", style="dim")

        for op in ops[:20]:
            table.add_row(
                op.timestamp.strftime("%Y-%m-%d %H:%M"),
                op.operation_type,
                op.source_path,
                op.destination_path or "-",
                op.status,
                "legacy / recheck hash before undo",
            )
        console.print(table)

    try:
        batches = container.audit_service.get_journal_history(vault)
        if batches:
            journal = Table(title="Reviewed Operation Plans")
            journal.add_column("Batch", style="cyan")
            journal.add_column("Status", style="yellow")
            journal.add_column("Plan", style="blue")
            journal.add_column("Files", style="green")
            for batch in batches:
                journal.add_row(batch["batch_id"], batch["status"], batch["plan_id"], str(len(batch["items"])))
                for item, assessment in zip(batch["items"], batch["assessment"]):
                    journal.add_row(
                        f"  {item['item_id']}",
                        f"{item['state']} / {assessment.classification}",
                        f"{item['source_path']} → {item['destination_path']}",
                        assessment.advice,
                    )
            console.print(journal)
    except Exception as e:
        console.print(f"[yellow]Could not load operation journal: {e}[/yellow]")


@app.command("undo")
def undo(
    operation_id: str = typer.Argument(None, help="Operation ID to undo (omit for last batch)"),
    journal_item: str | None = typer.Option(None, "--journal-item", help="Journal item ID to safely reverse"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Undo the last organisation batch or a specific operation."""
    container, vault = _require_active_vault()

    if not yes:
        if not typer.confirm("Are you sure you want to undo?", default=False):
            console.print("Cancelled.")
            return

    try:
        if journal_item:
            result = container.audit_service.undo_journal_item(journal_item, vault, approved=True)
            console.print(f"[green]Undid journal item {journal_item} in batch {result['batch_id']}[/green]")
        elif operation_id:
            result = container.audit_service.undo_operation(operation_id, vault)
            console.print(f"[green]Undid operation {operation_id}[/green]")
        else:
            batches = container.audit_service.get_journal_history(vault, limit=100)
            actionable = next((batch for batch in batches if batch["status"] == "committed" and
                               any(item.get("undo_status") == "none" for item in batch["items"])), None)
            if actionable:
                latest = actionable
                result = container.audit_service.undo_journal_batch(latest["batch_id"], vault, approved=True)
                console.print(f"Journal batch {result['batch_id']}: {result['status']}")
                for outcome in result["items"]:
                    console.print(f"  {outcome.get('item_id')}: {outcome['status']} {outcome.get('reason', '')}")
                return
            ops = container.audit_service.get_undoable_operations(vault.vault_id)
            if not ops:
                console.print("[yellow]No undoable operations found.[/yellow]")
                return
            last_batch = ops[0].batch_id
            if last_batch:
                report = container.audit_service.undo_batch_report(last_batch, vault)
                console.print(f"Legacy batch {last_batch}: {report['status']} ({len(report['successes'])} reversed, {len(report['refused'])} refused).")
                for refusal in report["refused"]:
                    console.print(f"  {refusal['operation_id']}: {refusal['reason']}")
            else:
                result = container.audit_service.undo_operation(ops[0].operation_id, vault)
                console.print(f"[green]Undid last operation.[/green]")
    except Exception as e:
        console.print(Panel(f"[red]Undo failed: {e}[/red]", title="Error"))
        raise typer.Exit(1)


@app.command("recover")
def recover(
    batch_id: str = typer.Argument(..., help="Operation batch ID to inspect or recover"),
    apply: bool = typer.Option(False, "--apply", help="Apply safe recovery actions after confirmation"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm recovery action"),
):
    """Inspect an interrupted batch; use --apply to retry/finalize safe items."""
    container, vault = _require_active_vault()
    try:
        service = container.audit_service
        assessments = service.inspect_journal_batch(batch_id, vault)
        for item in assessments:
            console.print(f"{item.item_id}: [bold]{item.classification}[/bold] — {item.advice}")
        if not apply:
            return
        if not yes and not typer.confirm("Apply the safe recovery actions shown above?", default=False):
            console.print("Cancelled.")
            return
        result = service.recover_journal_batch(batch_id, vault, approved=True)
        console.print(f"Batch {result['batch_id']}: {result['status']}")
        for item_id, status in result["items"]:
            console.print(f"  {item_id}: {status}")
    except Exception as e:
        console.print(Panel(f"[red]{e}[/red]", title="Recovery error"))
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
