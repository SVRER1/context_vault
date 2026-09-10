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
