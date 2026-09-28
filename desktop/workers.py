from PySide6.QtCore import QThread, Signal
import traceback
from contextvault.services.service_container import ServiceContainer
from contextvault.retrieval.search_models import SearchRequest

class BaseWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, service_container: ServiceContainer, *args, **kwargs):
        super().__init__()
        self.service_container = service_container
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            with self.service_container.database_lock:
                result = self.do_work()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"{str(e)}")

    def do_work(self):
        raise NotImplementedError()


class ScanWorker(BaseWorker):
    def do_work(self):
        self.progress.emit(0, 100, "Starting vault scan...")
        vault = self.service_container.vault
        if not vault:
            raise ValueError("No vault open")
        result = self.service_container.vault_service.scan_vault(vault, self.service_container.vault_db)
        self.progress.emit(100, 100, f"Scan complete: {len(result)} files.")
        return result


class IndexWorker(BaseWorker):
    def do_work(self):
        vault = self.service_container.vault
        if not vault:
            raise ValueError("No vault open")
            
        def on_prog(cur, tot, msg=""):
            pct = int((cur / tot) * 100) if tot > 0 else 0
            self.progress.emit(pct, 100, msg or "Indexing...")

        result = self.service_container.index_service.reconcile(progress_callback=on_prog)
        self.progress.emit(100, 100, "Indexing complete.")
        return result


class RAGWorker(BaseWorker):
    def do_work(self):
        query = self.kwargs.get("query")
        if not query:
            raise ValueError("Query is required")
        vault = self.service_container.vault
        if not vault:
            raise ValueError("No vault open")
        
        self.progress.emit(0, 100, "Retrieving and thinking...")
        result = self.service_container.rag_service.ask(
            query, vault.vault_id, subfolder=self.kwargs.get("subfolder")
        )
        self.progress.emit(100, 100, "Done.")
        return result


class SearchWorker(BaseWorker):
    def do_work(self):
        query = self.kwargs.get("query")
        rule = self.kwargs.get("rule")
        if not query and rule is None:
            raise ValueError("Enter search text or add a rule condition")
        vault = self.service_container.vault
        if not vault:
            raise ValueError("No vault open")
            
        self.progress.emit(0, 100, "Searching...")
        result = self.service_container.search_service.search(SearchRequest(
            vault_id=vault.vault_id,
            query=query or None,
            rule=rule,
            source_scope=self.kwargs.get("subfolder"),
        ))
        self.progress.emit(100, 100, f"Found {len(result.hits)} results.")
        return result


class OrganiseWorker(BaseWorker):
    def do_work(self):
        rules = self.kwargs.get("rules")
        if not rules:
            raise ValueError("Rules are required")
            
        self.progress.emit(0, 100, "Generating deterministic organisation plan...")
        plan = self.service_container.organisation_service.preview_plan(
            rules, subfolder=self.kwargs.get("subfolder")
        )
        self.progress.emit(100, 100, "Plan ready.")
        return plan


class ApplyOrganisationWorker(BaseWorker):
    def do_work(self):
        plan_id = self.kwargs.get("plan_id")
        digest = self.kwargs.get("digest")
        if not plan_id or not digest:
            raise ValueError("A persisted plan ID and digest are required")
            
        self.progress.emit(0, 100, "Applying organisation plan...")
        result = self.service_container.organisation_service.commit_plan(plan_id, digest, approved=True)
        self.progress.emit(100, 100, f"Operation batch status: {result.status}.")
        return result


class DuplicateWorker(BaseWorker):
    def do_work(self):
        self.progress.emit(0, 100, "Detecting duplicates...")
        exact, versions = self.service_container.organisation_service.detect_duplicates(
            subfolder=self.kwargs.get("subfolder")
        )
        self.progress.emit(100, 100, "Detection complete.")
        return {"exact": exact, "versions": versions}


class GenerateWorker(BaseWorker):
    def do_work(self):
        asset_type = self.kwargs.get("asset_type", "summary")
        topic = self.kwargs.get("topic")
        count = self.kwargs.get("count")
        filename = self.kwargs.get("filename")
        
        self.progress.emit(0, 100, f"Generating {asset_type}...")
        result = self.service_container.generation_service.generate(
            asset_type=asset_type,
            topic=topic,
            count=count,
            filename=filename,
            subfolder=self.kwargs.get("subfolder"),
        )
        self.progress.emit(100, 100, "Generation complete.")
        return result


class AgentWorker(BaseWorker):
    def do_work(self):
        query = self.kwargs.get("query")
        subfolder = self.kwargs.get("subfolder")
        if not query:
            raise ValueError("Query is required")
        vault = self.service_container.vault
        if not vault:
            raise ValueError("No vault open")

        self.progress.emit(0, 100, "Processing query...")
        result = self.service_container.orchestrator.handle_query(query, vault, subfolder=subfolder)
        self.progress.emit(100, 100, "Done.")
        return result
