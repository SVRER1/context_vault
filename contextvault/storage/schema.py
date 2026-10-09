VAULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS vaults (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    absolute_path TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    last_opened_at TIMESTAMP NOT NULL,
    last_indexed_at TIMESTAMP,
    file_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    index_version INTEGER DEFAULT 1
);
"""

FILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    created_time REAL NOT NULL,
    sha256 TEXT NOT NULL,
    mime_family TEXT NOT NULL,
    parser TEXT,
    parse_status TEXT DEFAULT 'pending',
    indexed_at TIMESTAMP,
    FOREIGN KEY (vault_id) REFERENCES vaults(id)
);
CREATE INDEX IF NOT EXISTS idx_files_vault_id ON files(vault_id);
CREATE INDEX IF NOT EXISTS idx_files_relative_path ON files(relative_path);
"""

CHUNKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    vault_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    page INTEGER,
    section TEXT,
    heading TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id),
    FOREIGN KEY (vault_id) REFERENCES vaults(id)
);
CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_vault_id ON chunks(vault_id);
"""

CLASSIFICATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS classifications (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    category TEXT NOT NULL,
    document_type TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id)
);
"""

OPERATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    vault_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    source_path TEXT NOT NULL,
    destination_path TEXT,
    hash_before TEXT,
    hash_after TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    user_approved BOOLEAN DEFAULT 0,
    batch_id TEXT,
    undo_status TEXT DEFAULT 'none',
    FOREIGN KEY (vault_id) REFERENCES vaults(id)
);
"""

OPERATION_BATCHES_SCHEMA = """
CREATE TABLE IF NOT EXISTS operation_batches (
    batch_id TEXT PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    vault_id TEXT NOT NULL,
    description TEXT,
    FOREIGN KEY (vault_id) REFERENCES vaults(id)
);
"""

GENERATED_ASSETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS generated_assets (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    source_chunks TEXT,
    source_files TEXT,
    source_scope TEXT,
    FOREIGN KEY (vault_id) REFERENCES vaults(id)
);
"""

SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ALL_SCHEMAS = [
    VAULTS_SCHEMA,
    FILES_SCHEMA,
    CHUNKS_SCHEMA,
    CLASSIFICATIONS_SCHEMA,
    OPERATIONS_SCHEMA,
    OPERATION_BATCHES_SCHEMA,
    GENERATED_ASSETS_SCHEMA,
    SETTINGS_SCHEMA
]

                                                                       
                                                                          
                                  
CURRENT_SCHEMA_VERSION = 5

MIGRATION_1_FILE_COLUMNS = {
    "path_key": "TEXT",
    "parent_path": "TEXT",
    "mime_type": "TEXT",
    "mtime_ns": "INTEGER",
    "ctime_ns": "INTEGER",
    "word_count": "INTEGER NOT NULL DEFAULT 0",
    "document_title": "TEXT",
    "document_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
    "extract_status": "TEXT NOT NULL DEFAULT 'pending'",
    "extract_error": "TEXT",
    "last_seen_scan": "TEXT",
}

MIGRATION_1_CHUNK_COLUMNS = {
    "line_start": "INTEGER",
    "line_end": "INTEGER",
    "slide": "INTEGER",
    "sheet": "TEXT",
    "cell_range": "TEXT",
    "char_start": "INTEGER",
    "char_end": "INTEGER",
    "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
}

FILE_TAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_tags (
    file_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    tag_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (file_id, tag_key),
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_file_tags_tag_key ON file_tags(tag_key);
"""

INDEX_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS index_runs (
    run_id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL,
    scope TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    discovered INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    moved INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    unchanged INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    truncated INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    FOREIGN KEY (vault_id) REFERENCES vaults(id)
);
CREATE INDEX IF NOT EXISTS idx_index_runs_vault_started
    ON index_runs(vault_id, started_at);
"""

CHUNKS_FTS5_SCHEMA = """
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    id UNINDEXED,
    file_id UNINDEXED,
    vault_id UNINDEXED,
    relative_path UNINDEXED,
    filename,
    text,
    heading,
    section,
    tokenize='unicode61 remove_diacritics 2'
);
"""

MIGRATION_2_OPERATION_PLANS_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_operation_plans (
    plan_id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL,
    scope TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    index_run_id TEXT,
    status TEXT NOT NULL,
    digest TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    FOREIGN KEY (vault_id) REFERENCES vaults(id)
);
CREATE INDEX IF NOT EXISTS idx_operation_plans_vault_created
    ON file_operation_plans(vault_id, created_at);
CREATE INDEX IF NOT EXISTS idx_operation_plans_status_expiry
    ON file_operation_plans(status, expires_at);
"""

MIGRATION_3_JOURNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS operation_batches_v3 (
    batch_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    vault_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error TEXT,
    FOREIGN KEY (plan_id) REFERENCES file_operation_plans(plan_id),
    FOREIGN KEY (vault_id) REFERENCES vaults(id)
);
CREATE TABLE IF NOT EXISTS operation_items_v3 (
    item_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    plan_item_index INTEGER NOT NULL,
    file_id TEXT NOT NULL,
    action TEXT NOT NULL,
    source_path TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    temp_path TEXT,
    before_hash TEXT NOT NULL,
    after_hash TEXT,
    expected_size INTEGER NOT NULL,
    state TEXT NOT NULL,
    error TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    index_applied INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES operation_batches_v3(batch_id)
);
CREATE INDEX IF NOT EXISTS idx_operation_batches_v3_vault_created
    ON operation_batches_v3(vault_id, created_at);
CREATE INDEX IF NOT EXISTS idx_operation_items_v3_batch_state
    ON operation_items_v3(batch_id, state);
"""
