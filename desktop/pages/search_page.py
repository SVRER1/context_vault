import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from desktop.widgets.rule_builder import RuleBuilder
from desktop.workers import SearchWorker


class SearchPage(QWidget):
    """Deterministic indexed search with the shared visual rule AST editor."""

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        layout = QVBoxLayout(self)
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search indexed content (optional when using rules)...")
        self.search_input.returnPressed.connect(self.perform_search)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.perform_search)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_btn)
        layout.addLayout(search_layout)
        self.rule_builder = RuleBuilder()
        self.rule_builder.add_condition()
        layout.addWidget(self.rule_builder)
        self.loading_label = QLabel("Searching indexed files...")
        self.loading_label.setVisible(False)
        layout.addWidget(self.loading_label)
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.open_result)
        layout.addWidget(self.results_list)
        tag_layout = QHBoxLayout()
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Tag for selected result")
        self.add_tag_btn = QPushButton("Add tag")
        self.remove_tag_btn = QPushButton("Remove tag")
        self.add_tag_btn.clicked.connect(lambda: self.change_tag(remove=False))
        self.remove_tag_btn.clicked.connect(lambda: self.change_tag(remove=True))
        tag_layout.addWidget(self.tag_input, 1)
        tag_layout.addWidget(self.add_tag_btn)
        tag_layout.addWidget(self.remove_tag_btn)
        layout.addLayout(tag_layout)
        self.worker = None

    def perform_search(self):
        query = self.search_input.text().strip()
        try:
            rule = self.rule_builder.build_rule()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid rule", str(exc))
            return
        if not query and rule is None:
            return
        self.results_list.clear()
        self.loading_label.setVisible(True)
        self.search_btn.setEnabled(False)
        self.worker = SearchWorker(
            self.app_context.service_container,
            query=query,
            rule=rule,
            subfolder=self.app_context.active_subfolder,
        )
        self.worker.finished.connect(self.handle_results)
        self.worker.error.connect(self.handle_error)
        self.worker.start()

    def handle_results(self, response):
        self.loading_label.setVisible(False)
        self.search_btn.setEnabled(True)
        for diagnostic in response.diagnostics:
            self.results_list.addItem(f"Index note: {diagnostic}")
        if response.unknown_ids:
            self.results_list.addItem(f"{len(response.unknown_ids)} file(s) have incomplete results.")
        if not response.hits:
            self.results_list.addItem("No results found.")
            return
        for hit in response.hits:
            passage = hit.passages[0] if hit.passages else None
            snippet = passage.snippet if passage else "No extracted passage; filename metadata matched."
            location = ""
            if passage:
                location = passage.heading or passage.section or ""
                if passage.page is not None:
                    location = f"Page {passage.page}" + (f" · {location}" if location else "")
                elif passage.line_start is not None:
                    location = f"Lines {passage.line_start}-{passage.line_end}" + (f" · {location}" if location else "")
            incomplete = "" if hit.content_complete else f" · extraction {hit.extract_status}"
            item = QListWidgetItem(
                f"{hit.filename} — Score: {hit.score:.3f}{incomplete}\n"
                f"{hit.relative_path}\n{location}\n{snippet}"
            )
            item.setData(Qt.ItemDataRole.UserRole, hit.absolute_path)
            item.setData(Qt.ItemDataRole.UserRole + 1, hit.file_id)
            item.setToolTip(f"{hit.absolute_path}\nType: {hit.mime_type or hit.extension}\n{location}")
            self.results_list.addItem(item)

    def handle_error(self, err_msg):
        self.loading_label.setVisible(False)
        self.search_btn.setEnabled(True)
        QMessageBox.critical(self, "Search Error", str(err_msg))

    def change_tag(self, *, remove: bool):
        item = self.results_list.currentItem()
        tag = self.tag_input.text().strip()
        file_id = item.data(Qt.ItemDataRole.UserRole + 1) if item else None
        if not file_id or not tag:
            QMessageBox.information(self, "Select a result", "Select a file result and enter a tag.")
            return
        try:
            container = self.app_context.service_container
            with container.database_lock:
                tags = (container.tag_service.remove(file_id, tag) if remove
                        else container.tag_service.add(file_id, tag))
            QMessageBox.information(self, "Tags updated", ", ".join(tags) if tags else "No tags remain.")
        except Exception as exc:
            QMessageBox.warning(self, "Tag update failed", str(exc))

    def open_result(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        elif path:
            QMessageBox.warning(self, "File Not Found", "The selected file could not be found.")
