import json
import logging
import re
from pathlib import Path
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional

from contextvault.core.models import FileRecord, ClassificationResult, OrganisationPlan, PlannedOperation
from contextvault.core.vault import Vault
from contextvault.llm.client import LLMClient
from contextvault.storage.database import Database
from contextvault.llm.prompts import CLASSIFICATION_PROMPT
from contextvault.organisation.rules import OrganisationRules
from contextvault.tools.peeker import ShallowPeeker

logger = logging.getLogger(__name__)


class SemanticOrganiser:
    def __init__(self, llm_client: Optional[LLMClient], db: Optional[Database] = None, retriever: Optional[Any] = None):
        self.llm_client = llm_client
        self.db = db
        self.retriever = retriever

    def classify_file(self, file_record: FileRecord, vault: Vault, rules: Optional[OrganisationRules] = None) -> ClassificationResult:
        file_path = vault.root_path / file_record.relative_path
        
                                                                        
        peek_res = ShallowPeeker.peek_file(file_path, max_lines=15)
        content_sample = peek_res.get("preview", "")

        custom_param = rules.custom_parameter if rules else None

        if not self.llm_client or not self.llm_client.is_available():
                                                                     
            fname = file_record.filename.lower()
            prev_lower = content_sample.lower()
            
            if custom_param:
                                                                                 
                for cat_candidate in re.split(r"[,;|\n]", custom_param):
                    c_clean = cat_candidate.strip().lower()
                    if c_clean and (c_clean in fname or c_clean in prev_lower):
                        return ClassificationResult(
                            category=cat_candidate.strip().title(),
                            document_type=file_record.mime_family,
                            confidence=0.85,
                            evidence=[file_record.filename],
                        )

            if any(w in fname or w in prev_lower for w in ("os", "kernel", "scheduling", "deadlock", "memory")):
                cat = "Operating Systems"
            elif any(w in fname or w in prev_lower for w in ("java", "python", "code", "def ", "class ", "script")):
                cat = "Code"
            elif any(w in fname or w in prev_lower for w in ("assignment", "homework", "task")):
                cat = "Assignments"
            elif any(w in fname or w in prev_lower for w in ("notes", "lecture", "slide")):
                cat = "Lecture Notes"
            elif file_record.mime_family == "data" or any(w in fname for w in ("sales", "grades", "metrics", "data", "report")):
                cat = "Data & Reports"
            else:
                cat = file_record.mime_family.capitalize()
                
            return ClassificationResult(
                category=cat,
                document_type=file_record.mime_family,
                confidence=0.7,
                evidence=[file_record.filename]
            )

        if custom_param:
            prompt = (
                f"You are organizing files based on this specific division parameter: '{custom_param}'.\n"
                f"Assign this file to exactly ONE folder name matching the parameter. Return ONLY a JSON object.\n\n"
                f"Filename: {file_record.filename}\n"
                f"Extension: {file_record.extension}\n"
                f"Content Preview (first 15 lines):\n{content_sample[:400]}\n\n"
                f'Output format: {{"category": "<folder name>", "document_type": "{file_record.mime_family}", "confidence": 0.9}}'
            )
        else:
            prompt = CLASSIFICATION_PROMPT.format(
                filename=file_record.filename,
                extension=file_record.extension,
                title=file_record.filename,
                content=content_sample[:400]
            )
        
        try:
            response = self.llm_client.generate(prompt)
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                data = json.loads(match.group())
                raw_cat = data.get("category", "General")
                                            
                clean_cat = re.sub(r'[\\/*?:"<>|]', "", str(raw_cat)).strip().title() or "General"
                return ClassificationResult(
                    category=clean_cat,
                    document_type=data.get("document_type", file_record.mime_family),
                    confidence=float(data.get("confidence", 0.7)),
                    evidence=data.get("evidence", [])
                )
        except Exception as e:
            logger.warning(f"Classification failed for {file_record.filename}: {e}")

        return ClassificationResult(
            category="General",
            document_type=file_record.mime_family,
            confidence=0.5,
            evidence=[]
        )

    def normalise_categories(self, categories: Dict[str, List[FileRecord]]) -> Dict[str, List[FileRecord]]:
        normalised: Dict[str, List[FileRecord]] = {}
        for cat, items in categories.items():
            clean_cat = re.sub(r"[^\w\s-]", "", cat).strip().title() or "General"
            matched = False
            for existing in list(normalised.keys()):
                if SequenceMatcher(None, clean_cat.lower(), existing.lower()).ratio() > 0.8:
                    normalised[existing].extend(items)
                    matched = True
                    break
            if not matched:
                normalised[clean_cat] = items
        return normalised

    def organise(self, files: List[FileRecord], vault: Vault, rules: OrganisationRules) -> OrganisationPlan:
        plan = OrganisationPlan(directories_to_create=[], operations=[], untouched_files=[])
        dirs_to_create = set()
        
        categorized_files: Dict[str, List[FileRecord]] = {}
        file_confidences: Dict[str, float] = {}

        for f in files:
            res = self.classify_file(f, vault, rules=rules)
            file_confidences[f.id] = res.confidence

            if res.confidence < rules.min_confidence:
                if rules.low_confidence_action == 'leave':
                    plan.untouched_files.append(f.relative_path)
                    continue
                else:
                    cat = "Review Needed"
            else:
                cat = res.category

            if cat not in categorized_files:
                categorized_files[cat] = []
            categorized_files[cat].append(f)

        normalised = self.normalise_categories(categorized_files)

        for category, cat_files in normalised.items():
            dirs_to_create.add(category)
            for f in cat_files:
                source_abs = vault.root_path / f.relative_path
                rel_target = f"{category}/{f.filename}"
                target_abs = vault.root_path / rel_target

                if source_abs.resolve() == target_abs.resolve():
                    plan.untouched_files.append(f.relative_path)
                    continue

                if target_abs.exists():
                    plan.untouched_files.append(f.relative_path)
                    plan.warnings.append(f"Destination already exists: {rel_target}. Skipped.")
                    continue

                plan.operations.append(PlannedOperation(
                    type="move",
                    source=f.relative_path,
                    destination=rel_target,
                    reason=f"Organised into '{category}'",
                    confidence=file_confidences.get(f.id, 0.7)
                ))

        plan.directories_to_create = sorted(list(dirs_to_create))
        return plan
