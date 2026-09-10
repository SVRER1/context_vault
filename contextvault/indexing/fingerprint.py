import hashlib
import os
from pathlib import Path
from contextvault.core.models import FileRecord

def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hex digest of a file safely."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def needs_rehash(file_record: FileRecord, current_stat: os.stat_result) -> bool:
    """Checks if mtime or size changed since last record."""
    if current_stat.st_size != file_record.size:
        return True
    if current_stat.st_mtime > file_record.mtime:
        return True
    return False

def verify_integrity(path: Path, expected_hash: str) -> bool:
    """Verifies that the file at path matches expected_hash."""
    try:
        current_hash = compute_sha256(path)
        return current_hash == expected_hash
    except OSError:
        return False
