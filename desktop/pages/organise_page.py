from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QComboBox, QSpinBox, QCheckBox, QPushButton, 
    QTreeWidget, QTreeWidgetItem, QMessageBox, QLabel, QLineEdit, QFrame
)
from desktop.workers import OrganiseWorker, ApplyOrganisationWorker
from contextvault.organisation.rules import OrganisationRules


class OrganisePage(QWidget):
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
                       
        header = QLabel("Vault Organisation & Directory Division")
        font = header.font()
        font.setPointSize(14)
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)
        
        subtitle = QLabel("Divide and structure files into subdirectories with hash-verified safety.")
        subtitle.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(subtitle)
        
                        
        controls_frame = QFrame()
        controls_frame.setStyleSheet("background-color: #1e293b; border-radius: 8px; padding: 10px;")
        form_layout = QFormLayout(controls_frame)
        form_layout.setSpacing(10)
        
        self.primary_combo = QComboBox()
        self.primary_combo.addItems([
            "By File Type / Extension (PDF, Code, Data, Documents)",
            "By File Family (Documents, Images, Code, Archives)",
            "By Content Subject / Topic (AI Categorized via 15-line peek)",
            "By Date Created/Modified (Year-Month)",
            "By Date Created/Modified (Year)",
            "By File Size (Tiny, Small, Medium, Large)",
            "Custom Division Parameter (User Defined)",
        ])
        self.primary_combo.currentIndexChanged.connect(self.on_division_changed)
        form_layout.addRow("Parameter of Division:", self.primary_combo)
        
                                                                
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText("e.g. Divide by course: CS101, Math, Physics | or by project: Alpha, Beta")
        self.custom_input.setVisible(False)
        form_layout.addRow("Custom Criteria:", self.custom_input)
        
        self.max_depth = QSpinBox()
        self.max_depth.setRange(1, 4)
        self.max_depth.setValue(2)
        form_layout.addRow("Max Folder Depth:", self.max_depth)
        
        self.preserve_cb = QCheckBox("Preserve existing subdirectories (don't flatten)")
        self.preserve_cb.setChecked(True)
        form_layout.addRow("", self.preserve_cb)
        
        self.preview_btn = QPushButton("Preview Organisation Plan")
        self.preview_btn.setStyleSheet("font-weight: bold; background-color: #0284c7; color: white; padding: 8px 16px; border-radius: 6px;")
        self.preview_btn.clicked.connect(self.generate_preview)
        form_layout.addRow("", self.preview_btn)
        
        layout.addWidget(controls_frame)
        
                        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #38bdf8; font-style: italic;")
        layout.addWidget(self.status_label)
        
                      
        self.preview_tree = QTreeWidget()
        self.preview_tree.setHeaderLabels(["Proposed Vault Directory Structure", "Action", "Details / Reason"])
        self.preview_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 8px;
                color: #f8fafc;
                font-size: 12px;
                padding: 6px;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: bold;
                border: none;
                padding: 6px;
            }
        """)
        layout.addWidget(self.preview_tree)
        
                           
        action_layout = QHBoxLayout()
        self.summary_label = QLabel("Summary: 0 files to move, 0 directories to create")
        self.summary_label.setStyleSheet("color: #94a3b8; font-weight: bold;")
        action_layout.addWidget(self.summary_label)
        
        self.apply_btn = QPushButton("Apply Organisation (Create Folders & Move Files)")
        self.apply_btn.setStyleSheet("background-color: #059669; color: white; font-weight: bold; padding: 8px 16px; border-radius: 6px;")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply_plan)
        
        self.cancel_btn = QPushButton("Reset Preview")
        self.cancel_btn.setStyleSheet("background-color: #475569; color: white; padding: 8px 12px; border-radius: 6px;")
        self.cancel_btn.clicked.connect(self.reset_preview)
        
        action_layout.addStretch()
        action_layout.addWidget(self.cancel_btn)
        action_layout.addWidget(self.apply_btn)
        
        layout.addLayout(action_layout)
        
        self.current_plan = None
        self.worker = None

    def on_division_changed(self, index):
        is_custom = "Custom" in self.primary_combo.currentText()
        self.custom_input.setVisible(is_custom)

    def _build_rules(self) -> OrganisationRules:
        text = self.primary_combo.currentText()
        custom_val = self.custom_input.text().strip() if self.custom_input.isVisible() else None
        
        if "Custom" in text:
            strategy = "semantic"
            primary = "custom"
        elif "Subject" in text:
            strategy = "semantic"
            primary = "subject"
        elif "Family" in text:
            strategy = "deterministic"
            primary = "file-family"
        elif "Year-Month" in text:
            strategy = "deterministic"
            primary = "date-month"
        elif "Year" in text:
            strategy = "deterministic"
            primary = "date-year"
        elif "Size" in text:
            strategy = "deterministic"
            primary = "size"
        else:
            strategy = "deterministic"
            primary = "file-type"

        return OrganisationRules(
            strategy=strategy,
            primary_grouping=primary,
            custom_parameter=custom_val,
            max_depth=self.max_depth.value(),
            preserve_existing=self.preserve_cb.isChecked(),
        )

    def generate_preview(self):
        vault = self.app_context.service_container.vault
        if not vault:
            QMessageBox.warning(self, "No Vault", "Please select a vault folder first.")
            return

        self.status_label.setText("Analyzing files and generating organisation plan...")
        self.preview_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        
        rules = self._build_rules()
        self.worker = OrganiseWorker(
            self.app_context.service_container,
            rules=rules,
            subfolder=self.app_context.active_subfolder,
        )
        self.worker.finished.connect(self.handle_preview_ready)
        self.worker.error.connect(self.handle_error)
        self.worker.start()

    def handle_preview_ready(self, plan):
        self.status_label.setText("Plan ready. Review proposed directories and file moves below.")
        self.preview_btn.setEnabled(True)
        self.current_plan = plan
        
        self.preview_tree.clear()
        
        self.preview_tree.setHeaderLabels(["Source path", "Action", "Destination / issue"])
        for op in plan.items:
            self.preview_tree.addTopLevelItem(QTreeWidgetItem([op.source, op.action, op.destination]))
        for issue in plan.conflicts:
            self.preview_tree.addTopLevelItem(QTreeWidgetItem([issue.path or "", "Conflict", issue.message]))
        for issue in (*plan.skips, *plan.warnings):
            self.preview_tree.addTopLevelItem(QTreeWidgetItem([issue.path or "", issue.code, issue.message]))

        self.summary_label.setText(
            f"Plan {plan.plan_id[:8]} · {len(plan.items)} operations · "
            f"{len(plan.conflicts)} conflicts · {len(plan.skips)} skipped"
        )
        self.apply_btn.setEnabled(bool(plan.items) and not plan.conflicts)

    def apply_plan(self):
        if not self.current_plan or not self.current_plan.items or self.current_plan.conflicts:
            return
        if self.current_plan.scope != self.app_context.active_subfolder:
            QMessageBox.warning(self, "Scope changed", "The selected directory changed after this preview. Generate a new plan before applying.")
            self.reset_preview()
            return
            
        reply = QMessageBox.question(
            self, "Confirm Organisation", 
            f"Commit plan {self.current_plan.plan_id[:8]} with {len(self.current_plan.items)} file operations?\n\n"
            "The system will recheck source fingerprints and destination collisions before changing files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.status_label.setText("Revalidating the plan and applying journaled operations...")
            self.apply_btn.setEnabled(False)
            
            self.worker = ApplyOrganisationWorker(
                self.app_context.service_container,
                plan_id=self.current_plan.plan_id,
                digest=self.current_plan.digest,
            )
            self.worker.finished.connect(self.handle_apply_done)
            self.worker.error.connect(self.handle_error)
            self.worker.start()

    def handle_apply_done(self, result):
        self.status_label.setText(f"Operation batch status: {result.status} ({result.batch_id}).")
        if result.status == "committed":
            QMessageBox.information(self, "Complete", f"Committed {len(result.completed)} operations.\nBatch: {result.batch_id}")
            self.reset_preview()
        else:
            QMessageBox.warning(self, "Recovery required", f"Batch {result.batch_id} stopped in {result.status}.\n{result.error or ''}")

    def handle_error(self, err_msg):
        self.status_label.setText("Error occurred during plan generation.")
        self.preview_btn.setEnabled(True)
        QMessageBox.critical(self, "Organisation Error", f"Failed to generate plan:\n{err_msg}")

    def reset_preview(self):
        self.preview_tree.clear()
        self.current_plan = None
        self.apply_btn.setEnabled(False)
        self.preview_btn.setEnabled(True)
        self.summary_label.setText("Summary: 0 files to move, 0 directories to create")
        self.status_label.setText("")
