from threading import Thread


class BaseWorker:
    def __init__(self, service_container, *args, **kwargs):
        self.service_container = service_container
        self.args = args
        self.kwargs = kwargs
        self.progress_callbacks = []
        self.finished_callbacks = []
        self.error_callbacks = []
        self.thread = None

    def on_progress(self, callback):
        self.progress_callbacks.append(callback)
        return self

    def on_finished(self, callback):
        self.finished_callbacks.append(callback)
        return self

    def on_error(self, callback):
        self.error_callbacks.append(callback)
        return self

    def emit_progress(self, current, total, message):
        for callback in self.progress_callbacks:
            callback(current, total, message)

    def start(self):
        self.thread = Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def run(self):
        try:
            result = self.do_work()
            for callback in self.finished_callbacks:
                callback(result)
        except Exception as exc:
            for callback in self.error_callbacks:
                callback(str(exc))

    def do_work(self):
        raise NotImplementedError


class ScanWorker(BaseWorker):
    def do_work(self):
        self.emit_progress(0, 100, "Starting vault scan...")
        vault = self.service_container.vault
        if not vault:
            raise ValueError("No vault open")
        result = self.service_container.vault_service.scan_vault(vault, self.service_container.vault_db)
        self.emit_progress(100, 100, f"Scan complete: {len(result)} files.")
        return result


class IndexWorker(BaseWorker):
    def do_work(self):
        vault = self.service_container.vault
        if not vault:
            raise ValueError("No vault open")

        def on_progress(current, total, message=""):
            self.emit_progress(current, total, message or "Preparing vault...")

        result = self.service_container.vault_service.index_vault(
            vault,
            self.service_container.vault_db,
            progress_callback=on_progress,
            ocr_client=self.service_container.llm_client,
        )
        self.emit_progress(100, 100, "Vault preparation complete.")
        return result


class RAGWorker(BaseWorker):
    def do_work(self):
        query = self.kwargs.get("query")
        vault = self.service_container.vault
        if not query or not vault:
            raise ValueError("A query and an open vault are required")
        self.emit_progress(0, 100, "Retrieving and thinking...")
        result = self.service_container.rag_service.ask(
            query, vault.vault_id, subfolder=self.kwargs.get("subfolder")
        )
        self.emit_progress(100, 100, "Done.")
        return result


class SearchWorker(BaseWorker):
    def do_work(self):
        query = self.kwargs.get("query")
        vault = self.service_container.vault
        if not query or not vault:
            raise ValueError("A query and an open vault are required")
        self.emit_progress(0, 100, "Searching...")
        result = self.service_container.rag_service.search(
            query, vault.vault_id, subfolder=self.kwargs.get("subfolder")
        )
        self.emit_progress(100, 100, f"Found {len(result)} results.")
        return result


class OrganiseWorker(BaseWorker):
    def do_work(self):
        rules = self.kwargs.get("rules")
        if not rules:
            raise ValueError("Rules are required")
        self.emit_progress(0, 100, "Generating organisation plan...")
        result = self.service_container.organisation_service.preview(
            rules, subfolder=self.kwargs.get("subfolder")
        )
        self.emit_progress(100, 100, "Plan ready.")
        return result


class ApplyOrganisationWorker(BaseWorker):
    def do_work(self):
        plan = self.kwargs.get("plan")
        if not plan:
            raise ValueError("Plan is required")
        self.emit_progress(0, 100, "Applying organisation plan...")
        result = self.service_container.organisation_service.apply(plan)
        self.emit_progress(100, 100, f"Applied {len(result)} operations.")
        return result


class DuplicateWorker(BaseWorker):
    def do_work(self):
        self.emit_progress(0, 100, "Detecting duplicates...")
        result = self.service_container.organisation_service.detect_duplicates(
            subfolder=self.kwargs.get("subfolder")
        )
        self.emit_progress(100, 100, "Detection complete.")
        return {"exact": result[0], "versions": result[1]}


class GenerateWorker(BaseWorker):
    def do_work(self):
        self.emit_progress(0, 100, "Generating artifact...")
        result = self.service_container.generation_service.generate(
            asset_type=self.kwargs.get("asset_type", "summary"),
            topic=self.kwargs.get("topic"),
            count=self.kwargs.get("count"),
            filename=self.kwargs.get("filename"),
            subfolder=self.kwargs.get("subfolder"),
        )
        self.emit_progress(100, 100, "Generation complete.")
        return result


class AgentWorker(BaseWorker):
    def do_work(self):
        query = self.kwargs.get("query")
        vault = self.service_container.vault
        if not query or not vault:
            raise ValueError("A query and an open vault are required")
        self.emit_progress(0, 100, "Processing query...")
        result = self.service_container.orchestrator.handle_query(
            query, vault, subfolder=self.kwargs.get("subfolder")
        )
        self.emit_progress(100, 100, "Done.")
        return result
