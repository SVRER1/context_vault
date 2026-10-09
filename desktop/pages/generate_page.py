import os
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, 
    QLineEdit, QSpinBox, QPushButton, QTextBrowser, QLabel, 
    QMessageBox, QTabWidget, QCheckBox
)
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from desktop.workers import GenerateWorker
from contextvault.tools.charts import ChartGenerator
from contextvault.generation.pdf_compiler import PDFCompiler


class GeneratePage(QWidget):
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        
        main_layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        
                                                                   
        self.doc_tab = QWidget()
        self._build_doc_tab()
        self.tabs.addTab(self.doc_tab, "Knowledge Artifacts & PDFs")
        
                                        
        self.chart_tab = QWidget()
        self._build_chart_tab()
        self.tabs.addTab(self.chart_tab, "Visual Charts & Graphs")
        
        main_layout.addWidget(self.tabs)
        self.worker = None

    def _build_doc_tab(self):
        layout = QVBoxLayout(self.doc_tab)
        form_layout = QFormLayout()
        
        self.asset_type_combo = QComboBox()
        self.asset_type_combo.addItems([
            "Summary", "Study Guide", "Revision Notes", 
            "Flashcards", "Quiz", "Timeline", "Vault Report"
        ])
        form_layout.addRow("Asset Type:", self.asset_type_combo)
        
        self.topic_input = QLineEdit()
        self.topic_input.setPlaceholderText("Optional: topic or subject focus")
        form_layout.addRow("Topic:", self.topic_input)
        
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 100)
        self.count_spin.setValue(10)
        self.count_spin.setEnabled(False)
        form_layout.addRow("Count (Flashcards/Quiz):", self.count_spin)
        self.asset_type_combo.currentTextChanged.connect(self.on_type_changed)
        
        self.pdf_cb = QCheckBox("Compile styled PDF artifact with cover & tables")
        self.pdf_cb.setChecked(True)
        form_layout.addRow("", self.pdf_cb)
        
        self.generate_btn = QPushButton("Generate Knowledge Artifact")
        self.generate_btn.setStyleSheet("font-weight: bold; background-color: #0284c7; color: white; padding: 6px 12px; border-radius: 4px;")
        self.generate_btn.clicked.connect(self.generate_content)
        form_layout.addRow("", self.generate_btn)
        
        layout.addLayout(form_layout)
        
        self.doc_status_label = QLabel("")
        layout.addWidget(self.doc_status_label)
        
        self.output_display = QTextBrowser()
        self.output_display.setOpenExternalLinks(True)
        layout.addWidget(self.output_display)

    def _build_chart_tab(self):
        layout = QVBoxLayout(self.chart_tab)
        form_layout = QFormLayout()
        
        file_row = QHBoxLayout()
        self.dataset_combo = QComboBox()
        self.refresh_files_btn = QPushButton("Scan Datasets")
        self.refresh_files_btn.clicked.connect(self.refresh_dataset_files)
        file_row.addWidget(self.dataset_combo)
        file_row.addWidget(self.refresh_files_btn)
        form_layout.addRow("Data File (.csv / .xlsx):", file_row)
        
        self.chart_type_combo = QComboBox()
        self.chart_type_combo.addItems(["Bar Chart", "Line Chart", "Scatter Plot", "Pie Chart"])
        form_layout.addRow("Chart Type:", self.chart_type_combo)
        
        self.chart_title_input = QLineEdit()
        self.chart_title_input.setPlaceholderText("Optional chart title")
        form_layout.addRow("Chart Title:", self.chart_title_input)
        
        self.chart_btn = QPushButton("Generate Visual Chart")
        self.chart_btn.setStyleSheet("font-weight: bold; background-color: #0d9488; color: white; padding: 6px 12px; border-radius: 4px;")
        self.chart_btn.clicked.connect(self.generate_chart)
        form_layout.addRow("", self.chart_btn)
        
        layout.addLayout(form_layout)
        
        self.chart_status_label = QLabel("")
        layout.addWidget(self.chart_status_label)
        
        self.chart_display = QTextBrowser()
        self.chart_display.setOpenExternalLinks(True)
        layout.addWidget(self.chart_display)

    def refresh_dataset_files(self):
        vault = self.app_context.service_container.vault
        self.dataset_combo.clear()
        if not vault:
            return

        files = list(vault.root_path.rglob("*.csv")) + list(vault.root_path.rglob("*.xlsx"))
        valid = [
            vault.relative_path(f) for f in files
            if not any(p in (".git", ".venv", ".contextvault", vault.generated_dir.name) for p in f.parts)
        ]
        for v in valid:
            self.dataset_combo.addItem(v)

    def on_type_changed(self, text):
        self.count_spin.setEnabled(text in ["Flashcards", "Quiz"])

    def generate_content(self):
        self.generate_btn.setEnabled(False)
        self.doc_status_label.setText("Generating knowledge artifact with the configured local Ollama model...")
        self.output_display.clear()
        
        params = {
            "asset_type": self.asset_type_combo.currentText().lower().replace(" ", "-"),
            "topic": self.topic_input.text().strip() or None,
            "subfolder": self.app_context.active_subfolder,
        }
        if self.asset_type_combo.currentText() in ["Flashcards", "Quiz"]:
            params["count"] = self.count_spin.value()
            
        self.worker = GenerateWorker(self.app_context.service_container, **params)
        self.worker.finished.connect(self.handle_result)
        self.worker.error.connect(self.handle_error)
        self.worker.start()

    def handle_result(self, result):
        self.generate_btn.setEnabled(True)
        self.doc_status_label.setText("Artifact generated successfully.")
        
        vault = self.app_context.service_container.vault
        rel_p = getattr(result, "relative_path", "")
        abs_p = vault.root_path / rel_p if vault else Path(rel_p)
        
        content = ""
        if abs_p.exists():
            try:
                content = abs_p.read_text(encoding="utf-8")
            except Exception:
                content = str(result)

        scope_text = self.app_context.active_subfolder or "Entire Vault"
        info_md = f"### Asset Created: `{rel_p}`\n- **Source scope**: `{scope_text}`\n"
        
                                  
        if self.pdf_cb.isChecked() and vault and abs_p.exists():
            try:
                pdf_res = PDFCompiler.compile_pdf(
                    vault=vault,
                    title=getattr(result, "title", "Knowledge Asset"),
                    content_markdown=content,
                    output_filename=abs_p.stem + ".pdf",
                )
                info_md += f"- **Compiled PDF**: `{pdf_res['relative_path']}`\n"
            except Exception as e:
                info_md += f"- _(PDF compilation note: {e})_\n"

        info_md += f"\n---\n\n{content}"
        self.output_display.setMarkdown(info_md)

    def generate_chart(self):
        vault = self.app_context.service_container.vault
        if not vault:
            QMessageBox.warning(self, "No Vault", "Please open a vault first.")
            return

        file_rel = self.dataset_combo.currentText()
        if not file_rel:
            QMessageBox.warning(self, "No Dataset", "Please select a dataset file.")
            return

        chart_type = self.chart_type_combo.currentText().split()[0].lower()
        title = self.chart_title_input.text().strip() or None

        self.chart_status_label.setText("Plotting visual chart...")
        try:
            info = ChartGenerator.generate_chart(
                vault=vault,
                relative_path=file_rel,
                chart_type=chart_type,
                title=title,
            )
            self.chart_status_label.setText("Chart generated successfully.")
            md = (
                f"### Chart Plotted: {info['title']}\n"
                f"- **Data Source**: `{info['image_relative_path']}`\n"
                f"- **Points Count**: {info['points_count']}\n\n"
                f"File location: `{info['image_relative_path']}`"
            )
            self.chart_display.setMarkdown(md)
        except Exception as e:
            self.chart_status_label.setText(f"Failed: {e}")
            QMessageBox.critical(self, "Chart Error", str(e))

    def handle_error(self, err_msg):
        self.generate_btn.setEnabled(True)
        self.doc_status_label.setText("Error during generation.")
        QMessageBox.critical(self, "Generation Error", err_msg)
