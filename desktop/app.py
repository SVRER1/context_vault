import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import requests

from contextvault.core.models import OrganisationPlan
from contextvault.organisation.rules import OrganisationRules
from contextvault.retrieval.filesystem_policy import is_ignored_source_path
from contextvault.services.service_container import ServiceContainer
from contextvault.tools.charts import ChartGenerator


class AppContext:
    def __init__(self):
        self.service_container = ServiceContainer()
        self.active_vault_path = None
        self.active_subfolder = None


class DesktopAPI:
    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()
        self.context = AppContext()
        self.window = None
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gitpost-ui")
        self.jobs = {}
        self.lock = threading.RLock()

    def attach_window(self, window):
        self.window = window

    def _json(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if hasattr(value, "model_dump"):
            return self._json(value.model_dump())
        if isinstance(value, dict):
            return {str(key): self._json(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json(item) for item in value]
        if hasattr(value, "__dict__"):
            return self._json(vars(value))
        return str(value)

    def _vault(self):
        vault = self.context.service_container.vault
        if not vault:
            raise ValueError("No vault is open")
        return vault

    def _recent(self):
        try:
            return [self._json(value) for value in self.context.service_container.vault_service.list_vaults()]
        except Exception:
            return []

    def _scopes(self):
        vault = self.context.service_container.vault
        if not vault:
            return []
        generated = self.context.service_container.config.generated_output_folder
        scopes = set()
        for root, directories, files in os.walk(vault.root_path):
            root_path = Path(root)
            directories[:] = [
                name for name in directories
                if not is_ignored_source_path(root_path / name, generated)
            ]
            if root_path != vault.root_path:
                scopes.add(str(root_path.relative_to(vault.root_path)).replace("\\", "/"))
        return sorted(scopes)

    def _state(self):
        vault = self.context.service_container.vault
        if not vault:
            return {
                "open": False,
                "recent": self._recent(),
                "model": self.context.service_container.config.ollama_model,
                "llm_online": False,
            }
        status = self.context.service_container.vault_service.get_vault_status(vault)
        llm = self.context.service_container.llm_client
        return {
            "open": True,
            "vault": {
                "id": vault.vault_id,
                "name": vault.display_name,
                "path": str(vault.root_path),
            },
            "scope": self.context.active_subfolder,
            "scopes": self._scopes(),
            "files": status.get("file_count", 0),
            "cached_passages": status.get("chunk_count", 0),
            "model": self.context.service_container.config.ollama_model,
            "llm_online": bool(llm and llm.is_available()),
        }

    def boot(self):
        return self._state()

    def recent_vaults(self):
        return self._recent()

    def select_folder(self):
        if not self.window:
            return None
        import webview
        selected = self.window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
        return selected[0] if selected else None

    def set_scope(self, scope):
        vault = self._vault()
        scope = (scope or "").strip().strip("/\\") or None
        if scope:
            vault.scope_root(scope)
        self.context.active_subfolder = scope
        return self._state()

    def open_path(self, relative_path):
        vault = self._vault()
        target = vault.absolute_path(relative_path)
        if sys.platform.startswith("win"):
            os.startfile(str(target))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return True

    def start_job(self, action, payload=None):
        job_id = uuid.uuid4().hex
        with self.lock:
            self.jobs[job_id] = {"status": "queued", "message": "Queued"}
        future = self.executor.submit(self._run_job, job_id, action, payload or {})
        with self.lock:
            self.jobs[job_id]["future"] = future
        return {"job_id": job_id}

    def job_status(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return {"status": "missing", "error": "Job not found"}
            result = dict(job)
        result.pop("future", None)
        return result

    def _run_job(self, job_id, action, payload):
        with self.lock:
            self.jobs[job_id]["status"] = "running"
            self.jobs[job_id]["message"] = action
        try:
            value = self._execute(action, payload)
            with self.lock:
                self.jobs[job_id].update(status="done", result=self._json(value), message="Complete")
        except Exception as exc:
            with self.lock:
                self.jobs[job_id].update(status="error", error=str(exc), message="Failed")

    def _execute(self, action, payload):
        if action == "open_vault":
            path = str(Path(payload["path"]).resolve())
            self.context.service_container.open_vault(path)
            self.context.active_vault_path = path
            self.context.active_subfolder = None
            return self._state()
        if action == "prepare":
            vault = self._vault()
            return self.context.service_container.vault_service.index_vault(
                vault,
                self.context.service_container.vault_db,
                ocr_client=self.context.service_container.llm_client,
            )
        if action == "ask":
            vault = self._vault()
            return self.context.service_container.orchestrator.handle_query(
                payload["query"], vault, subfolder=self.context.active_subfolder
            )
        if action == "search":
            vault = self._vault()
            return self.context.service_container.rag_service.search(
                payload["query"], vault.vault_id, subfolder=self.context.active_subfolder
            )
        if action == "generate":
            return self.context.service_container.generation_service.generate(
                asset_type=payload.get("asset_type", "summary"),
                topic=payload.get("topic") or None,
                count=payload.get("count"),
                subfolder=self.context.active_subfolder,
            )
        if action == "chart":
            return ChartGenerator.generate_chart(
                vault=self._vault(),
                relative_path=payload["relative_path"],
                chart_type=payload.get("chart_type", "bar"),
                title=payload.get("title") or None,
            )
        if action == "organise_preview":
            rules = OrganisationRules(**payload["rules"])
            return self.context.service_container.organisation_service.preview(
                rules, subfolder=self.context.active_subfolder
            )
        if action == "organise_apply":
            plan = OrganisationPlan.model_validate(payload["plan"])
            return self.context.service_container.organisation_service.apply(plan)
        if action == "duplicates":
            result = self.context.service_container.organisation_service.detect_duplicates(
                subfolder=self.context.active_subfolder
            )
            return {"exact": result[0], "versions": result[1]}
        raise ValueError(f"Unknown desktop action: {action}")

    def datasets(self):
        vault = self._vault()
        scope = vault.scope_root(self.context.active_subfolder)
        generated = self.context.service_container.config.generated_output_folder
        result = []
        for path in scope.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".csv", ".xlsx"} and not is_ignored_source_path(path, generated):
                result.append(vault.relative_path(path))
        return sorted(result)

    def audit(self):
        vault = self._vault()
        return self.context.service_container.audit_service.get_operations(vault.vault_id, limit=100)

    def undo_operation(self, operation_id):
        return self.context.service_container.audit_service.undo_operation(operation_id, self._vault())

    def undo_last_batch(self):
        vault = self._vault()
        undoable = self.context.service_container.audit_service.get_undoable_operations(vault.vault_id)
        if not undoable:
            return []
        if undoable[0].batch_id:
            return self.context.service_container.audit_service.undo_batch(undoable[0].batch_id, vault)
        return [self.context.service_container.audit_service.undo_operation(undoable[0].operation_id, vault)]

    def settings(self):
        config = self.context.service_container.config
        return {
            "ollama_base_url": config.ollama_base_url,
            "ollama_model": config.ollama_model,
            "temperature": config.temperature,
            "retrieval_max_candidates": config.retrieval_max_candidates,
            "generated_output_folder": config.generated_output_folder,
        }

    def installed_models(self, url=None):
        endpoint = (url or self.context.service_container.config.ollama_base_url).rstrip("/")
        response = requests.get(f"{endpoint}/api/tags", timeout=5)
        response.raise_for_status()
        return [item.get("name") for item in response.json().get("models", []) if item.get("name")]

    def save_settings(self, values):
        config = self.context.service_container.config
        config.ollama_base_url = values.get("ollama_base_url", config.ollama_base_url).strip()
        config.ollama_model = values.get("ollama_model", config.ollama_model).strip()
        config.temperature = float(values.get("temperature", config.temperature))
        config.retrieval_max_candidates = int(values.get("retrieval_max_candidates", config.retrieval_max_candidates))
        config.generated_output_folder = values.get("generated_output_folder", config.generated_output_folder).strip()
        config.save()
        client = self.context.service_container._llm_client
        if client:
            client.base_url = config.ollama_base_url
            client.model = config.ollama_model
        return self.settings()

    def shutdown(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
        return True


class ContextVaultApp:
    pages = {
        "Chat & Studio": "chat",
        "Search": "search",
        "Organise": "organise",
        "Duplicates": "duplicates",
        "Generate": "generate",
        "Audit": "audit",
        "Settings": "settings",
    }

    def __init__(self):
        self.project_root = Path(__file__).resolve().parent.parent
        self.api = DesktopAPI(self.project_root)
        self.window = None

    def start(self):
        import webview
        page = (self.project_root / "desktop" / "web" / "index.html").resolve().as_uri()
        self.window = webview.create_window(
            "Context Vault",
            page,
            js_api=self.api,
            width=1280,
            height=860,
            min_size=(980, 680),
            text_select=True,
        )
        self.api.attach_window(self.window)
        webview.start(debug=False)

    def windowTitle(self):
        return "Context Vault"

    def close(self):
        self.api.shutdown()
        if self.window:
            self.window.destroy()
