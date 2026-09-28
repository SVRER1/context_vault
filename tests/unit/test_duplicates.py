from contextvault.core.models import FileRecord
from contextvault.duplicates.exact import ExactDuplicateDetector
from contextvault.duplicates.versions import VersionDetector

def test_exact_duplicates():
    detector = ExactDuplicateDetector()
    files = [
        FileRecord(
            id="1", vault_id="v1", relative_path="report.pdf", filename="report.pdf",
            extension=".pdf", size=1000, mtime=100.0, created_time=100.0,
            sha256="hash_abc", mime_family="document"
        ),
        FileRecord(
            id="2", vault_id="v1", relative_path="backup/report_copy.pdf", filename="report_copy.pdf",
            extension=".pdf", size=1000, mtime=105.0, created_time=105.0,
            sha256="hash_abc", mime_family="document"
        ),
        FileRecord(
            id="3", vault_id="v1", relative_path="different.pdf", filename="different.pdf",
            extension=".pdf", size=2000, mtime=110.0, created_time=110.0,
            sha256="hash_xyz", mime_family="document"
        )
    ]
    
    dups = detector.detect(files)
    assert len(dups) == 1
    assert dups[0].group_type == "exact"
    assert len(dups[0].files) == 2
    assert dups[0].hash == "hash_abc"

def test_version_detection():
    detector = VersionDetector()
    files = [
        FileRecord(
            id="1", vault_id="v1", relative_path="assignment.docx", filename="assignment.docx",
            extension=".docx", size=1000, mtime=100.0, created_time=100.0,
            sha256="hash_1", mime_family="document"
        ),
        FileRecord(
            id="2", vault_id="v1", relative_path="assignment_v2.docx", filename="assignment_v2.docx",
            extension=".docx", size=1100, mtime=110.0, created_time=110.0,
            sha256="hash_2", mime_family="document"
        ),
        FileRecord(
            id="3", vault_id="v1", relative_path="assignment_final.docx", filename="assignment_final.docx",
            extension=".docx", size=1200, mtime=120.0, created_time=120.0,
            sha256="hash_3", mime_family="document"
        ),
        FileRecord(
            id="4", vault_id="v1", relative_path="unrelated.docx", filename="unrelated.docx",
            extension=".docx", size=500, mtime=90.0, created_time=90.0,
            sha256="hash_4", mime_family="document"
        ),
    ]
    
    versions = detector.detect(files)
    assert len(versions) == 1
    assert versions[0].group_type == "version"
    assert len(versions[0].files) == 3
