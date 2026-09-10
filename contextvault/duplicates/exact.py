from typing import List, Dict
from contextvault.core.models import FileRecord
from contextvault.duplicates.models import DuplicateGroup

class ExactDuplicateDetector:
    def detect(self, files: List[FileRecord]) -> List[DuplicateGroup]:
        groups: Dict[str, List[FileRecord]] = {}
        for file in files:
            if not file.sha256:
                continue
            if file.sha256 not in groups:
                groups[file.sha256] = []
            groups[file.sha256].append(file)
            
        result = []
        for h, grp in groups.items():
            if len(grp) >= 2:
                result.append(DuplicateGroup(
                    group_type='exact',
                    hash=h,
                    files=grp,
                    confidence=1.0,
                    reason=f"Identical SHA-256 hash: {h}"
                ))
                
        result.sort(key=lambda x: len(x.files), reverse=True)
        return result
