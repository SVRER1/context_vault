import time
import threading
import os
from pathlib import Path
from typing import Callable, Dict
import hashlib

class FileWatcher:
    """A simple polling-based file watcher for the vault root."""
    
    def __init__(self, vault_root: Path, callback: Callable[[Dict[str, list]], None], interval_seconds: int = 30):
        self.vault_root = Path(vault_root)
        self.callback = callback
        self.interval = interval_seconds
        self._running = False
        self._thread = None
        self._file_hashes: Dict[str, str] = {}
        self._last_modified_times: Dict[str, float] = {}

    def _get_file_hash(self, filepath: Path) -> str:
        h = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    def start(self):
        """Starts the watcher thread."""
        if self._running:
            return
        self._running = True
        self._scan_initial()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stops the watcher thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.interval + 1)

    def _scan_initial(self):
        for root, _, files in os.walk(self.vault_root):
            for file in files:
                filepath = Path(root) / file
                try:
                    mtime = filepath.stat().st_mtime
                    self._last_modified_times[str(filepath)] = mtime
                    self._file_hashes[str(filepath)] = self._get_file_hash(filepath)
                except Exception:
                    pass

    def _check_changes(self):
        current_files = set()
        new_files = []
        modified_files = []
        deleted_files = []

        for root, _, files in os.walk(self.vault_root):
            for file in files:
                filepath = Path(root) / file
                path_str = str(filepath)
                current_files.add(path_str)

                try:
                    mtime = filepath.stat().st_mtime
                    
                    if path_str not in self._last_modified_times:
                        self._last_modified_times[path_str] = mtime
                        self._file_hashes[path_str] = self._get_file_hash(filepath)
                        new_files.append(filepath)
                    elif mtime > self._last_modified_times[path_str]:
                                                 
                        new_hash = self._get_file_hash(filepath)
                        if new_hash != self._file_hashes.get(path_str):
                            self._last_modified_times[path_str] = mtime
                            self._file_hashes[path_str] = new_hash
                            modified_files.append(filepath)
                except Exception:
                    pass

                           
        for known_path in list(self._last_modified_times.keys()):
            if known_path not in current_files:
                deleted_files.append(Path(known_path))
                del self._last_modified_times[known_path]
                if known_path in self._file_hashes:
                    del self._file_hashes[known_path]

        if new_files or modified_files or deleted_files:
            changes = {
                "new": new_files,
                "modified": modified_files,
                "deleted": deleted_files
            }
            self.callback(changes)

    def _watch_loop(self):
        while self._running:
            time.sleep(self.interval)
            self._check_changes()
