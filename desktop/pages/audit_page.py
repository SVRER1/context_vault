from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox)
from PySide6.QtCore import Qt

class AuditPage(QWidget):
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        
        layout = QVBoxLayout(self)
        
        
        btn_layout = QHBoxLayout()
        self.undo_btn = QPushButton("Undo Selected Operation")
        self.undo_btn.clicked.connect(self.undo_selected)
        self.undo_batch_btn = QPushButton("Undo Last Batch")
        self.undo_batch_btn.clicked.connect(self.undo_last_batch)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.load_audit_log)
        self.recover_btn = QPushButton("Inspect / Recover Selected Batch")
        self.recover_btn.clicked.connect(self.recover_selected_batch)
        
        btn_layout.addWidget(self.undo_btn)
        btn_layout.addWidget(self.undo_batch_btn)
        btn_layout.addWidget(self.recover_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.refresh_btn)
        layout.addLayout(btn_layout)
        
        
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Time", "Operation", "Source", "Destination", "Status", "Undo / Recovery", "Journal ID"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

    def showEvent(self, event):
        super().showEvent(event)
        self.load_audit_log()

    def load_audit_log(self):
        self.table.setRowCount(0)
        container = self.app_context.service_container
        vault = container.vault
        if not vault:
            return

        try:
            with container.database_lock:
                ops = container.audit_service.get_operations(vault.vault_id, limit=100)
                batches = container.audit_service.get_journal_history(vault, limit=100)
            for op in ops:
                row = self.table.rowCount()
                self.table.insertRow(row)
                
                time_str = op.timestamp.strftime("%Y-%m-%d %H:%M:%S") if hasattr(op.timestamp, "strftime") else str(op.timestamp)
                item_time = QTableWidgetItem(time_str)
                item_time.setData(Qt.ItemDataRole.UserRole, op.operation_id)
                
                self.table.setItem(row, 0, item_time)
                self.table.setItem(row, 1, QTableWidgetItem(op.operation_type))
                self.table.setItem(row, 2, QTableWidgetItem(op.source_path))
                self.table.setItem(row, 3, QTableWidgetItem(op.destination_path or "-"))
                self.table.setItem(row, 4, QTableWidgetItem(op.status))
                self.table.setItem(row, 5, QTableWidgetItem(op.undo_status))
                self.table.setItem(row, 6, QTableWidgetItem("legacy / hash checked"))
                item_time.setData(Qt.ItemDataRole.UserRole, ("legacy", op.operation_id))
            for batch in batches:
                for operation, assessment in zip(batch["items"], batch["assessment"]):
                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    item_time = QTableWidgetItem(batch["created_at"])
                    item_time.setData(Qt.ItemDataRole.UserRole, ("journal", operation["item_id"], batch["batch_id"]))
                    self.table.setItem(row, 0, item_time)
                    self.table.setItem(row, 1, QTableWidgetItem(operation["action"]))
                    self.table.setItem(row, 2, QTableWidgetItem(operation["source_path"]))
                    self.table.setItem(row, 3, QTableWidgetItem(operation["destination_path"]))
                    self.table.setItem(row, 4, QTableWidgetItem(f"{batch['status']} / {operation['state']}"))
                    undo_state = operation.get("undo_status", "none")
                    self.table.setItem(row, 5, QTableWidgetItem(f"{undo_state} / {assessment.classification}: {assessment.advice}"))
                    self.table.setItem(row, 6, QTableWidgetItem(operation["item_id"]))
        except Exception as e:
            QMessageBox.warning(self, "Audit history", f"Could not load complete history: {e}")

    def undo_selected(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Select Row", "Please select an operation to undo.")
            return
            
        row = selected_rows[0].row()
        item = self.table.item(row, 0)
        identity = item.data(Qt.ItemDataRole.UserRole)
        
        reply = QMessageBox.question(
            self, "Confirm Undo", "Reverse this move only if its recorded bytes are still at the destination and the original path is free?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            container = self.app_context.service_container
            vault = container.vault
            try:
                with container.database_lock:
                    if identity[0] == "journal":
                        result = container.audit_service.undo_journal_item(identity[1], vault, approved=True)
                    else:
                        result = container.audit_service.undo_operation(identity[1], vault)
                QMessageBox.information(self, "Undo Success", "The verified operation was reversed.")
            except Exception as e:
                QMessageBox.critical(self, "Undo Failed", f"Could not undo: {e}")
            self.load_audit_log()

    def undo_last_batch(self):
        reply = QMessageBox.question(
            self, "Confirm Batch Undo", "Are you sure you want to undo the last batch of operations?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            container = self.app_context.service_container
            vault = container.vault
            try:
                with container.database_lock:
                    batches = container.audit_service.get_journal_history(vault, limit=100)
                actionable = next((batch for batch in batches if batch["status"] == "committed" and
                                   any(item.get("undo_status") == "none" for item in batch["items"])), None)
                if actionable:
                    with container.database_lock:
                        result = container.audit_service.undo_journal_batch(actionable["batch_id"], vault, approved=True)
                    QMessageBox.information(self, "Undo", f"Journal batch status: {result['status']}.")
                    self.load_audit_log()
                    return
                with container.database_lock:
                    undoable = container.audit_service.get_undoable_operations(vault.vault_id)
                if not undoable:
                    QMessageBox.information(self, "Undo", "No operations available to undo.")
                    return
                last_batch = undoable[0].batch_id
                if last_batch:
                    with container.database_lock:
                        report = container.audit_service.undo_batch_report(last_batch, vault)
                    refusals = "\n".join(item["reason"] for item in report["refused"][:5])
                    QMessageBox.information(self, "Undo", f"Batch status: {report['status']}\nReversed {len(report['successes'])}; refused {len(report['refused'])}.\n{refusals}")
                else:
                    with container.database_lock:
                        container.audit_service.undo_operation(undoable[0].operation_id, vault)
                    QMessageBox.information(self, "Undo Success", "Undid last operation.")
            except Exception as e:
                QMessageBox.critical(self, "Undo Failed", f"Could not undo batch: {e}")
            self.load_audit_log()

    def recover_selected_batch(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Select Batch", "Select a journal item from the batch to inspect.")
            return
        identity = self.table.item(selected_rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if not identity or identity[0] != "journal":
            QMessageBox.information(self, "Recovery", "Selected row is a legacy audit record and has no recovery journal.")
            return
        container = self.app_context.service_container
        vault = container.vault
        try:
            with container.database_lock:
                assessments = container.audit_service.inspect_journal_batch(identity[2], vault)
            details = "\n".join(f"{item.classification}: {item.advice}" for item in assessments)
            if not any(item.classification in {"safe_to_retry", "safe_to_finalize"} for item in assessments):
                QMessageBox.information(self, "Recovery inspection", details)
                return
            reply = QMessageBox.question(self, "Confirm recovery", f"{details}\n\nApply safe retries/finalization?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                with container.database_lock:
                    result = container.audit_service.recover_journal_batch(identity[2], vault, approved=True)
                QMessageBox.information(self, "Recovery", f"Batch status: {result['status']}")
                self.load_audit_log()
        except Exception as exc:
            QMessageBox.critical(self, "Recovery failed", str(exc))
