import hashlib
from contextvault.indexing.fingerprint import compute_sha256, verify_integrity

def test_stable_sha256(tmp_path):
    file_a = tmp_path / "a.txt"
    file_a.write_text("Context Vault Invariant Test", encoding="utf-8")
    
    expected = hashlib.sha256(b"Context Vault Invariant Test").hexdigest()
    assert compute_sha256(file_a) == expected
    assert verify_integrity(file_a, expected) is True

def test_different_content_different_hash(tmp_path):
    f1 = tmp_path / "f1.txt"
    f2 = tmp_path / "f2.txt"
    f1.write_text("Hello World", encoding="utf-8")
    f2.write_text("Hello World!", encoding="utf-8")
    
    h1 = compute_sha256(f1)
    h2 = compute_sha256(f2)
    assert h1 != h2
    assert verify_integrity(f1, h2) is False
