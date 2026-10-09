import os
import subprocess
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QTableWidget, 
                               QTableWidgetItem, QHeaderView, QLabel, QMessageBox, QMenu)
from PySide6.QtCore import Qt
from desktop.workers import DuplicateWorker

class DuplicatesPage(QWidget):
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        
        layout = QVBoxLayout(self)
        
                         
        self.detect_btn = QPushButton("Detect Duplicates")
        self.detect_btn.clicked.connect(self.detect_duplicates)
        layout.addWidget(self.detect_btn)
        
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        
                                
        layout.addWidget(QLabel("Exact Duplicates (Grouped by Hash)"))
        self.exact_table = self.create_table()
        layout.addWidget(self.exact_table)
        
                                 
        layout.addWidget(QLabel("Possible Versions (Grouped by Similarity)"))
        self.versions_table = self.create_table()
        layout.addWidget(self.versions_table)
        
        self.worker = None

    def create_table(self):
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Filename", "Path", "Size", "Hash/Score"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos, t=table: self.show_context_menu(pos, t))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return table

    def show_context_menu(self, pos, table):
        item = table.itemAt(pos)
        if not item:
            return
            
        row = item.row()
        path_item = table.item(row, 1)
        if not path_item:
            return
            
        path = path_item.text()
        
        menu = QMenu(self)
        reveal_action = menu.addAction("Reveal in folder")
        
        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == reveal_action:
            if os.path.exists(path):
                                       
                subprocess.Popen(rf'explorer /select,"{path}"')
            else:
                QMessageBox.warning(self, "Error", "File no longer exists.")

    def detect_duplicates(self):
        self.detect_btn.setEnabled(False)
        self.status_label.setText("Scanning for duplicates...")
        
        self.worker = DuplicateWorker(
            self.app_context.service_container,
            subfolder=self.app_context.active_subfolder,
        )
        self.worker.finished.connect(self.handle_results)
        self.worker.error.connect(self.handle_error)
        self.worker.start()

    def handle_results(self, result):
        self.detect_btn.setEnabled(True)
        self.status_label.setText("Scan complete.")
        
        self.exact_table.setRowCount(0)
        self.versions_table.setRowCount(0)
        
        exact_groups = result.get("exact", []) if isinstance(result, dict) else getattr(result, "exact", [])
        vault = self.app_context.service_container.vault
        
        for group in exact_groups:
            files = getattr(group, "files", group if isinstance(group, list) else [])
            h = getattr(group, "hash", "") or ""
            for f in files:
                row = self.exact_table.rowCount()
                self.exact_table.insertRow(row)
                fname = getattr(f, "filename", os.path.basename(str(f)))
                rel_p = getattr(f, "relative_path", str(f))
                abs_p = str(vault.root_path / rel_p) if vault else rel_p
                sz = getattr(f, "size", 0)
                
                self.exact_table.setItem(row, 0, QTableWidgetItem(fname))
                self.exact_table.setItem(row, 1, QTableWidgetItem(abs_p))
                self.exact_table.setItem(row, 2, QTableWidgetItem(f"{sz:,} B"))
                self.exact_table.setItem(row, 3, QTableWidgetItem(h[:16] + "..." if len(h) > 16 else h))

        versions_groups = result.get("versions", []) if isinstance(result, dict) else getattr(result, "versions", [])
        for group in versions_groups:
            files = getattr(group, "files", group if isinstance(group, list) else [])
            reason = getattr(group, "reason", "Probable version")
            for f in files:
                row = self.versions_table.rowCount()
                self.versions_table.insertRow(row)
                fname = getattr(f, "filename", os.path.basename(str(f)))
                rel_p = getattr(f, "relative_path", str(f))
                abs_p = str(vault.root_path / rel_p) if vault else rel_p
                sz = getattr(f, "size", 0)
                
                self.versions_table.setItem(row, 0, QTableWidgetItem(fname))
                self.versions_table.setItem(row, 1, QTableWidgetItem(abs_p))
                self.versions_table.setItem(row, 2, QTableWidgetItem(f"{sz:,} B"))
                self.versions_table.setItem(row, 3, QTableWidgetItem(reason))

    def handle_error(self, err_msg):
        self.detect_btn.setEnabled(True)
        self.status_label.setText("Error occurred.")
        QMessageBox.critical(self, "Error", err_msg)
