from typing import List
from pathlib import Path
from difflib import SequenceMatcher
import re
from contextvault.core.models import FileRecord
from contextvault.duplicates.models import DuplicateGroup

class VersionDetector:
    def detect(self, files: List[FileRecord]) -> List[DuplicateGroup]:
        groups = []
        processed = set()
        
        patterns = [r'_v\d+', r'_final\d*', r'_copy\d*', r'\(\d+\)', r'_old', r'_new\d*', r'_draft', r'_revised']
        
        for i, file1 in enumerate(files):
            if file1.id in processed:
                continue
                
            current_group = [file1]
            p1 = Path(file1.filename)
            
            for j, file2 in enumerate(files[i+1:]):
                if file2.id in processed:
                    continue
                
                p2 = Path(file2.filename)
                
                if p1.suffix.lower() != p2.suffix.lower():
                    continue
                    
                                                                        
                if file1.sha256 and file2.sha256 and file1.sha256 == file2.sha256:
                    continue
                    
                sim = SequenceMatcher(None, p1.stem.lower(), p2.stem.lower()).ratio()
                
                is_version = False
                if sim > 0.7:
                    is_version = True
                else:
                    for pat in patterns:
                        if re.search(pat, p1.stem.lower()) or re.search(pat, p2.stem.lower()):
                            stem1 = re.sub(pat, '', p1.stem.lower())
                            stem2 = re.sub(pat, '', p2.stem.lower())
                            if SequenceMatcher(None, stem1, stem2).ratio() > 0.75:
                                is_version = True
                                break
                                
                if is_version:
                    current_group.append(file2)
                    processed.add(file2.id)
                    
            if len(current_group) > 1:
                groups.append(DuplicateGroup(
                    group_type='version',
                    hash=None,
                    files=current_group,
                    confidence=0.85,
                    reason=f"Probable revisions or versions of '{file1.filename}'"
                ))
            processed.add(file1.id)
            
        return groups
