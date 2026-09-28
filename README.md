# Context Vault

Context Vault is a local file indexing, deterministic search, and safe organization tool for Windows. Its shared Python core serves both the Typer CLI and the PySide6 desktop app. SQLite and FTS5 power indexing, rules, and ranked passage search; an LLM is optional and is only requested for generated answers or artifacts.

For architecture, data flow, implementation approaches, and a file-by-file map across six domains, see [SOFTWARE_GUIDE.md](SOFTWARE_GUIDE.md).

## Install and start

Requires Python 3.11 or newer. Install with the project metadata below, or use `pip install -r requirements.txt` for runtime dependencies.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
cvault --help
```

Open a folder once to register it as the active vault. Search reconciles its index automatically; use `scan` to reconcile explicitly or `index` to see extraction statistics.

```powershell
cvault open "C:\Users\you\Documents\Coursework"
cvault scan
cvault search "vector database"
cvault query 'type:pdf AND content:"operating systems" AND NOT content:assignment'
cvault ask "Where are deadlocks discussed?"
```

`ask` returns deterministic ranked evidence and excerpts by default. `cvault ask QUESTION --synthesize` asks the optional artifact provider to produce prose from that retrieved evidence. Without a configured/available provider, indexing, search, rules, file operations, history, and recovery still work.

## Query language

Supported fields include `name`, `path`, `extension`/`type`, `mime`, `content`, `tag`, `hash`, `size`, `modified`, and `created`. Boolean groups support `AND`, `OR`, `NOT`, and parentheses. Quoted content values match phrases. Use `~` for bounded filename/path regular expressions; comparisons apply to size and timestamps.

```text
type:pdf AND content:"vector database"
(extension:pdf OR extension:docx) AND content:"operating systems"
content:retrieval AND NOT content:assignment
name~"^lecture-[0-9]+" AND size>2MB
modified>=2026-01-01 AND tag:exam
```

The GUI rule builder emits the same validated AST as the CLI parser. It supports metadata and content predicates, AND/OR grouping, nested groups, and NOT. Query matching is deterministic; phrase and term retrieval use SQLite FTS5/BM25. Search results include file paths, scores, excerpts, source locations when extractors provide them, and incomplete-extraction diagnostics.

## Index and extraction

Each registered vault has a local SQLite index outside the source tree under `%LOCALAPPDATA%\ContextVault\vaults\`. Incremental reconciliation tracks file IDs, paths, size, timestamps, SHA-256, MIME, tags, extraction status, and located passages. Unchanged files avoid repeat hashing and extraction. Search and rule execution reconcile before querying; `cvault scan` explicitly reconciles too.

Text, Markdown, PDF, DOCX, PPTX, CSV, JSON, HTML, and source-code extraction are supported through modular extractors. Passage metadata can include pages, headings, sections, lines, sheets, and cell ranges. Unsupported, unreadable, or truncated files are marked as incomplete so their absence from content matches is not reported as certain. SQLite must include FTS5.

The configured `Generated/` directory and Context Vault internal data are excluded from source indexing. A scope such as `--scope "Course Notes"` narrows search and operations to that folder inside the vault.

## Preview and commit file operations

File changes use persisted immutable plans. Preview resolves rules, validates every destination, reports exact source-to-destination mappings and conflicts, and does not change files. Commit requires the plan ID and rechecks fingerprints and collisions.

```powershell
cvault move --where 'type:pdf AND content:retrieval' --into "Research"
cvault route --where 'type:pdf' --into "PDFs"
cvault apply PLAN_ID
cvault audit
cvault undo
```

`organise`, `move`, `copy`, `rename`, and `route` are preview-only until `apply PLAN_ID`. Use `--yes` only when you want to skip the CLI confirmation for a reviewed saved plan. Destinations are never overwritten. Operations are journaled per item; a failed batch can be partial and recovery inspects actual source/destination hashes before retrying or finalizing. Undo is offered only where the recorded paths and hashes still make reversal safe; copy operations are not represented as reversible moves.

Tags are metadata and do not change file bytes:

```powershell
cvault tag add notes.md exam
cvault query 'tag:exam AND content:retrieval'
cvault tag remove notes.md exam
```

## Desktop application

```powershell
cvault desktop
python -m desktop.main
```

The desktop search page uses ranked indexed retrieval and a visual rule builder. Organization and chat previews show saved plans before commit. Audit displays journal state, recovery guidance, and safe undo eligibility. Search, tags, organization, and audit remain available when no model is configured.

## Optional artifact generation

Ollama is optional. Configure its endpoint/model in Settings when you want synthesized answers or generated study guides, summaries, notes, flashcards, quizzes, or reports. The provider is created lazily and checked only for a generation request. It receives retrieved evidence, not authority to discover files or select filesystem destinations. Generated files are written beneath `Generated/` and do not become source content.

## Tests

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
```

The suite covers migrations, incremental extraction/indexing, parser and retrieval behavior, query and GUI parity, collision and failure handling, journal recovery and undo, and operation without Ollama. FTS5 availability is required. Platform-specific crash/recovery behavior is tested with fault injection; real hardware and filesystem failures can still vary by volume and permissions.
