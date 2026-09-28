import os
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLineEdit, QPushButton, QLabel, QMessageBox, QTextBrowser, 
    QFrame, QComboBox, QTabWidget, QSpinBox, QCheckBox, 
    QSplitter, QListWidget, QListWidgetItem, QSizePolicy
)
from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QFont

from desktop.workers import AgentWorker, ApplyOrganisationWorker, GenerateWorker
from contextvault.tools.charts import ChartGenerator


class MessageBubble(QFrame):
    """Custom compact chat bubble that fits its content without stretching excessively."""
    
    def __init__(self, sender: str, text: str, is_user: bool = False, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        
        
        sender_lbl = QLabel(sender)
        s_font = sender_lbl.font()
        s_font.setBold(True)
        s_font.setPointSize(10)
        sender_lbl.setFont(s_font)
        
        if is_user:
            sender_lbl.setStyleSheet("color: #bae6fd;")
            self.setStyleSheet("""
                QFrame {
                    background-color: #0284c7;
                    border-radius: 12px;
                    border: none;
                }
            """)
        else:
            sender_lbl.setStyleSheet("color: #38bdf8;")
            self.setStyleSheet("""
                QFrame {
                    background-color: #1e293b;
                    border-radius: 12px;
                    border: 1px solid #334155;
                }
            """)
            
        layout.addWidget(sender_lbl)
        
        
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setMarkdown(text)
        self.browser.setStyleSheet("""
            QTextBrowser {
                background: transparent;
                border: none;
                color: #f8fafc;
                font-size: 13px;
                padding: 0px;
            }
        """)
        self.browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        
        self.browser.document().setTextWidth(600)
        doc_height = self.browser.document().size().height()
        self.browser.setFixedHeight(max(24, int(doc_height) + 10))
        self.browser.setMaximumWidth(620)
        
        layout.addWidget(self.browser)
        self.setMaximumWidth(660)


class ChatPage(QWidget):
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)
        
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)
        
        
        chat_container = QWidget()
        chat_vlayout = QVBoxLayout(chat_container)
        chat_vlayout.setContentsMargins(0, 0, 0, 0)
        chat_vlayout.setSpacing(8)
        
        
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        
        scope_icon = QLabel("🎯 Source of Truth (Evidence Scope):")
        scope_icon.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px;")
        top_bar.addWidget(scope_icon)
        
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("📁 Entire Vault (All Files)")
        self.scope_combo.setStyleSheet("""
            QComboBox {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #0284c7;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                min-width: 200px;
            }
            QComboBox QAbstractItemView {
                background-color: #1e293b;
                color: #f8fafc;
                selection-background-color: #0284c7;
            }
        """)
        top_bar.addWidget(self.scope_combo)
        self.scope_combo.currentIndexChanged.connect(self.on_scope_changed)
        
        self.refresh_scope_btn = QPushButton("🔄")
        self.refresh_scope_btn.setToolTip("Rescan vault subdirectories")
        self.refresh_scope_btn.setFixedSize(28, 28)
        self.refresh_scope_btn.setStyleSheet("background-color: #334155; color: white; border-radius: 4px;")
        self.refresh_scope_btn.clicked.connect(self.populate_subdirectories)
        top_bar.addWidget(self.refresh_scope_btn)
        
        top_bar.addStretch()
        
        self.toggle_studio_btn = QPushButton("📋 Generation Studio")
        self.toggle_studio_btn.setStyleSheet("background-color: #334155; color: #38bdf8; font-weight: bold; padding: 5px 12px; border-radius: 6px;")
        self.toggle_studio_btn.clicked.connect(self.toggle_studio)
        top_bar.addWidget(self.toggle_studio_btn)
        
        chat_vlayout.addLayout(top_bar)
        
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; background-color: #0f172a; }")
        
        self.chat_inner = QWidget()
        self.chat_inner.setStyleSheet("background-color: transparent;")
        self.chat_layout = QVBoxLayout(self.chat_inner)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(10)
        self.scroll_area.setWidget(self.chat_inner)
        chat_vlayout.addWidget(self.scroll_area)
        
        
        self.loading_label = QLabel("Processing with the configured local Ollama model...")
        self.loading_label.setStyleSheet("color: #38bdf8; font-style: italic; font-size: 11px;")
        self.loading_label.setVisible(False)
        chat_vlayout.addWidget(self.loading_label)
        
        
        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(6)
        chips = [
            ("⚡ Organise by Type", "organise files by extension"),
            ("📁 Organise by Subject", "organise files by subject"),
            ("👁️ Peek Files (15 lines)", "peek into directory"),
            ("🔍 Duplicates", "find duplicate files"),
            ("📊 Plot Chart", "generate a chart of my data"),
            ("📄 Study Guide PDF", "generate a study guide as PDF"),
        ]
        for label, query_text in chips:
            btn = QPushButton(label)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #cbd5e1;
                    border: 1px solid #334155;
                    border-radius: 12px;
                    padding: 3px 10px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #334155;
                    color: #38bdf8;
                    border-color: #0284c7;
                }
            """)
            btn.clicked.connect(lambda checked=False, q=query_text: self.quick_chip_clicked(q))
            chips_layout.addWidget(btn)
        chips_layout.addStretch()
        chat_vlayout.addLayout(chips_layout)
        
        
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask a question, request directory division, search, or generate artifacts...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 9px 14px;
                color: #f8fafc;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #0284c7;
            }
        """)
        self.input_field.returnPressed.connect(self.send_message)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: white;
                font-weight: bold;
                border-radius: 8px;
                padding: 9px 18px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #0369a1;
            }
        """)
        self.send_btn.clicked.connect(self.send_message)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_btn)
        chat_vlayout.addLayout(input_layout)
        
        self.splitter.addWidget(chat_container)
        
        
        self.studio_panel = QFrame()
        self.studio_panel.setFixedWidth(380)
        self.studio_panel.setStyleSheet("background-color: #1e293b; border-radius: 8px; border: 1px solid #334155;")
        studio_layout = QVBoxLayout(self.studio_panel)
        studio_layout.setContentsMargins(12, 12, 12, 12)
        studio_layout.setSpacing(10)
        
        studio_title = QLabel("Generation & Artifact Studio")
        s_font = studio_title.font()
        s_font.setBold(True)
        s_font.setPointSize(12)
        studio_title.setFont(s_font)
        studio_title.setStyleSheet("color: #f8fafc;")
        studio_layout.addWidget(studio_title)
        
        self.studio_tabs = QTabWidget()
        self.studio_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #334155; background-color: #0f172a; border-radius: 6px; }
            QTabBar::tab { background: #1e293b; color: #94a3b8; padding: 6px 10px; font-size: 11px; }
            QTabBar::tab:selected { background: #0284c7; color: white; font-weight: bold; }
        """)
        
        
        doc_tab = QWidget()
        doc_layout = QVBoxLayout(doc_tab)
        doc_layout.setContentsMargins(8, 8, 8, 8)
        doc_layout.setSpacing(8)
        
        doc_layout.addWidget(QLabel("Asset Type:"))
        self.gen_type_combo = QComboBox()
        self.gen_type_combo.addItems(["Summary", "Study Guide", "Revision Notes", "Flashcards", "Quiz", "Timeline", "Vault Report"])
        self.gen_type_combo.setStyleSheet("background-color: #1e293b; color: #f8fafc; padding: 4px; border: 1px solid #475569;")
        doc_layout.addWidget(self.gen_type_combo)
        
        doc_layout.addWidget(QLabel("Topic (optional):"))
        self.gen_topic_input = QLineEdit()
        self.gen_topic_input.setPlaceholderText("e.g. Object Oriented Programming")
        self.gen_topic_input.setStyleSheet("background-color: #1e293b; color: #f8fafc; padding: 4px; border: 1px solid #475569;")
        doc_layout.addWidget(self.gen_topic_input)
        
        doc_layout.addWidget(QLabel("Count (for flashcards/quiz):"))
        self.gen_count_spin = QSpinBox()
        self.gen_count_spin.setRange(3, 20)
        self.gen_count_spin.setValue(5)
        self.gen_count_spin.setStyleSheet("background-color: #1e293b; color: #f8fafc; padding: 4px; border: 1px solid #475569;")
        doc_layout.addWidget(self.gen_count_spin)
        
        self.gen_pdf_cb = QCheckBox("Compile styled PDF artifact")
        self.gen_pdf_cb.setChecked(True)
        self.gen_pdf_cb.setStyleSheet("color: #f8fafc;")
        doc_layout.addWidget(self.gen_pdf_cb)
        
        self.gen_btn = QPushButton("Generate Document Artifact")
        self.gen_btn.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; padding: 8px; border-radius: 6px;")
        self.gen_btn.clicked.connect(self.generate_document_artifact)
        doc_layout.addWidget(self.gen_btn)
        doc_layout.addStretch()
        
        self.studio_tabs.addTab(doc_tab, "Documents")
        
        
        chart_tab = QWidget()
        chart_layout = QVBoxLayout(chart_tab)
        chart_layout.setContentsMargins(8, 8, 8, 8)
        chart_layout.setSpacing(8)
        
        chart_layout.addWidget(QLabel("Dataset File (CSV/XLSX):"))
        self.chart_file_combo = QComboBox()
        self.chart_file_combo.setStyleSheet("background-color: #1e293b; color: #f8fafc; padding: 4px; border: 1px solid #475569;")
        self.chart_file_combo.currentIndexChanged.connect(self.on_chart_dataset_selected)
        chart_layout.addWidget(self.chart_file_combo)
        
        chart_layout.addWidget(QLabel("Chart Type:"))
        self.chart_type_combo = QComboBox()
        self.chart_type_combo.addItems(["Bar Chart", "Line Chart", "Scatter Plot", "Pie Chart"])
        self.chart_type_combo.setStyleSheet("background-color: #1e293b; color: #f8fafc; padding: 4px; border: 1px solid #475569;")
        chart_layout.addWidget(self.chart_type_combo)
        
        chart_layout.addWidget(QLabel("X-Axis Column:"))
        self.chart_x_combo = QComboBox()
        self.chart_x_combo.setStyleSheet("background-color: #1e293b; color: #f8fafc; padding: 4px; border: 1px solid #475569;")
        chart_layout.addWidget(self.chart_x_combo)
        
        chart_layout.addWidget(QLabel("Y-Axis Column:"))
        self.chart_y_combo = QComboBox()
        self.chart_y_combo.setStyleSheet("background-color: #1e293b; color: #f8fafc; padding: 4px; border: 1px solid #475569;")
        chart_layout.addWidget(self.chart_y_combo)
        
        self.plot_btn = QPushButton("Plot and Save Visual Chart")
        self.plot_btn.setStyleSheet("background-color: #06b6d4; color: black; font-weight: bold; padding: 8px; border-radius: 6px;")
        self.plot_btn.clicked.connect(self.plot_visual_chart)
        chart_layout.addWidget(self.plot_btn)
        chart_layout.addStretch()
        
        self.studio_tabs.addTab(chart_tab, "Charts")
        
        
        recent_tab = QWidget()
        recent_layout = QVBoxLayout(recent_tab)
        recent_layout.setContentsMargins(8, 8, 8, 8)
        recent_layout.setSpacing(6)
        
        recent_layout.addWidget(QLabel("Generated Artifacts in Vault:"))
        self.artifacts_list = QListWidget()
        self.artifacts_list.setStyleSheet("background-color: #0f172a; color: #f8fafc; border: 1px solid #334155; border-radius: 4px;")
        self.artifacts_list.itemDoubleClicked.connect(self.open_recent_artifact)
        recent_layout.addWidget(self.artifacts_list)
        
        self.refresh_artifacts_btn = QPushButton("Refresh Artifacts")
        self.refresh_artifacts_btn.setStyleSheet("background-color: #334155; color: white; padding: 4px;")
        self.refresh_artifacts_btn.clicked.connect(self.load_recent_artifacts)
        recent_layout.addWidget(self.refresh_artifacts_btn)
        
        self.studio_tabs.addTab(recent_tab, "Files")
        
        studio_layout.addWidget(self.studio_tabs)
        self.splitter.addWidget(self.studio_panel)
        
        self.splitter.setSizes([750, 380])
        self.worker = None

    def showEvent(self, event):
        super().showEvent(event)
        self.populate_subdirectories()
        self.populate_datasets()
        self.load_recent_artifacts()

    def toggle_studio(self):
        self.studio_panel.setVisible(not self.studio_panel.isVisible())
        if self.studio_panel.isVisible():
            self.toggle_studio_btn.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; padding: 5px 12px; border-radius: 6px;")
        else:
            self.toggle_studio_btn.setStyleSheet("background-color: #334155; color: #94a3b8; font-weight: bold; padding: 5px 12px; border-radius: 6px;")

    def populate_subdirectories(self):
        vault = self.app_context.service_container.vault
        if not vault or not vault.root_path.exists():
            return
            
        cur = self.scope_combo.currentText()
        self.scope_combo.clear()
        self.scope_combo.addItem("📁 Entire Vault (All Files)")
        
        ignore_dirs = {".git", ".venv", ".contextvault", "__pycache__", "node_modules", vault.generated_dir.name}
        try:
            for root, dirs, files in os.walk(vault.root_path):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                rel = os.path.relpath(root, vault.root_path)
                if rel != ".":
                    clean_rel = rel.replace("\\", "/")
                    self.scope_combo.addItem(f"📂 {clean_rel}/")
        except Exception:
            pass
            
        
        idx = self.scope_combo.findText(cur)
        if idx >= 0:
            self.scope_combo.setCurrentIndex(idx)
        self.on_scope_changed(self.scope_combo.currentIndex())

    def on_scope_changed(self, _index=0):
        """Publish the selected source-of-truth directory to all app pages."""
        self.app_context.active_subfolder = self.get_current_subfolder()
        if hasattr(self, "chart_file_combo"):
            self.populate_datasets()

    def get_current_subfolder(self) -> str | None:
        text = self.scope_combo.currentText()
        if "Entire Vault" in text or not text.startswith("📂 "):
            return None
        return text.replace("📂 ", "").rstrip("/")

    def quick_chip_clicked(self, query_text):
        self.input_field.setText(query_text)
        self.send_message()

    def send_message(self):
        query = self.input_field.text().strip()
        if not query:
            return

        self.input_field.clear()
        self.add_message("You", query, is_user=True)

        self.loading_label.setVisible(True)
        self.input_field.setEnabled(False)
        self.send_btn.setEnabled(False)

        subfolder = self.get_current_subfolder()
        self.worker = AgentWorker(self.app_context.service_container, query=query, subfolder=subfolder)
        self.worker.finished.connect(self.handle_response)
        self.worker.error.connect(self.handle_error)
        self.worker.start()

    def add_message(self, sender: str, text: str, is_user: bool = False):
        bubble = MessageBubble(sender, text, is_user=is_user, parent=self)
        bubble.browser.anchorClicked.connect(self.open_citation)
        
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        if is_user:
            layout.addStretch()
            layout.addWidget(bubble)
        else:
            layout.addWidget(bubble)
            layout.addStretch()

        self.chat_layout.addLayout(layout)
        self._scroll_to_bottom()

    def handle_response(self, result):
        self.loading_label.setVisible(False)
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)

        text = getattr(result, "content", "") or getattr(result, "answer", str(result))
        citations = getattr(result, "citations", [])
        result_type = getattr(result, "result_type", "")
        plan = getattr(result, "data", {}).get("plan") if hasattr(result, "data") and isinstance(result.data, dict) else None

        subfolder = self.get_current_subfolder()
        if subfolder:
            text = f"_Scoped to directory: `{subfolder}/`_\n\n" + text

        if citations:
            text += "\n\n---\n**Sources:**\n"
            vault = self.app_context.service_container.vault
            for i, src in enumerate(citations, 1):
                page_info = f" (page {src.page})" if src.page else ""
                heading_info = f" - _{src.heading}_" if src.heading else ""
                abs_path = str(vault.root_path / src.file_path) if vault else src.file_path
                file_url = QUrl.fromLocalFile(abs_path).toString()
                text += f"- [{i}] [{src.file_path}{page_info}{heading_info}]({file_url})\n"

        self.add_message("Context Vault", text, is_user=False)

        
        if result_type == "organisation_plan" and plan and plan.items:
            self._render_interactive_plan_card(plan)

    def _render_interactive_plan_card(self, plan):
        card = QFrame()
        card.setStyleSheet("background-color: #064e3b; border: 1px solid #059669; border-radius: 10px; padding: 12px;")
        card.setMaximumWidth(660)
        c_layout = QVBoxLayout(card)
        c_layout.setSpacing(6)

        title = QLabel(f"⚡ Reviewed Plan: {len(plan.items)} operations · {len(plan.conflicts)} conflicts")
        title.setStyleSheet("font-weight: bold; color: #ecfdf5; font-size: 12px;")
        c_layout.addWidget(title)

        mapping_summary = "\n".join(f"{item.source} → {item.destination}" for item in plan.items[:5])
        issues = [f"CONFLICT: {issue.path or ''} {issue.message}" for issue in plan.conflicts]
        issues.extend(f"{issue.code}: {issue.path or ''} {issue.message}" for issue in (*plan.skips, *plan.warnings))
        mapping_summary = "\n".join(f"{item.source} -> {item.destination} [{item.action}]" for item in plan.items)
        detail = mapping_summary + ("\n\n" + "\n".join(issues) if issues else "")
        desc = QLabel(f"{detail}\nPlan ID: {plan.plan_id}\nScope: {plan.scope or 'Entire vault'}")
        desc.setWordWrap(True)
        desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        desc.setStyleSheet("color: #a7f3d0; font-size: 11px;")
        c_layout.addWidget(desc)

        apply_btn = QPushButton("Commit Reviewed Plan")
        apply_btn.setEnabled(not plan.conflicts)
        apply_btn.setStyleSheet("background-color: #059669; color: white; font-weight: bold; border-radius: 6px; padding: 8px 16px;")
        apply_btn.clicked.connect(lambda: self._apply_plan_from_chat(plan, apply_btn))
        c_layout.addWidget(apply_btn)

        self.chat_layout.addWidget(card)
        self._scroll_to_bottom()

    def _apply_plan_from_chat(self, plan, btn):
        if plan.scope != self.app_context.active_subfolder:
            QMessageBox.warning(self, "Scope changed", "The selected directory changed after this preview. Request a new plan before applying.")
            btn.setEnabled(False)
            btn.setText("Preview is stale")
            return
        mappings = "\n".join(f"{item.source} -> {item.destination}" for item in plan.items)
        reply = QMessageBox.question(
            self, "Confirm reviewed plan",
            f"Commit plan {plan.plan_id}? This revalidates files and destinations.\n\n{mappings}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        btn.setEnabled(False)
        btn.setText("Revalidating and applying journaled operations...")
        worker = ApplyOrganisationWorker(
            self.app_context.service_container, plan_id=plan.plan_id, digest=plan.digest
        )
        
        def on_applied(result):
            if result.status != "committed":
                btn.setEnabled(True)
                btn.setText("Recovery required")
                self.add_message("System", f"Batch {result.batch_id} needs recovery: {result.error or result.status}")
                return
            btn.setText("Plan Successfully Applied!")
            btn.setStyleSheet("background-color: #065f46; color: #6ee7b7; border-radius: 6px; padding: 6px;")
            self.add_message("System", f"Committed {len(result.completed)} verified operations. Batch {result.batch_id} is recorded in history.")
            self.populate_subdirectories()
            
        def on_error(err):
            btn.setEnabled(True)
            btn.setText("Retry Apply")
            QMessageBox.critical(self, "Error", f"Failed to apply plan: {err}")

        worker.finished.connect(on_applied)
        worker.error.connect(on_error)
        worker.start()

    def _scroll_to_bottom(self):
        self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        )

    def handle_error(self, err_msg):
        self.loading_label.setVisible(False)
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Failed to process request:\n{err_msg}")

    def open_citation(self, url: QUrl):
        path = url.toLocalFile() if url.isLocalFile() else url.toString()
        if os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.warning(self, "File Not Found", f"Cannot find referenced file:\n{path}")

    
    def generate_document_artifact(self):
        vault = self.app_context.service_container.vault
        if not vault:
            QMessageBox.warning(self, "No Vault", "Please open a vault first.")
            return

        atype = self.gen_type_combo.currentText().lower().replace(" ", "-")
        topic = self.gen_topic_input.text().strip() or None
        count = self.gen_count_spin.value()
        compile_pdf = self.gen_pdf_cb.isChecked()

        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("Generating with local Ollama...")

        def do_gen():
            gen_service = self.app_context.service_container.generation_service
            subfolder = self.get_current_subfolder()
            asset = gen_service.generate(
                asset_type=atype, topic=topic, count=count, subfolder=subfolder
            )
            pdf_path = None
            if compile_pdf:
                try:
                    from contextvault.generation.pdf_compiler import PDFCompiler
                    markdown_path = vault.root_path / asset.relative_path
                    pdf_info = PDFCompiler.compile_pdf(
                        title=asset.title,
                        vault=vault,
                        content_markdown=markdown_path.read_text(encoding="utf-8"),
                        output_filename=f"{asset.filename.rsplit('.', 1)[0]}.pdf",
                    )
                    pdf_path = vault.root_path / pdf_info["relative_path"]
                except Exception as e:
                    raise RuntimeError(f"PDF compilation failed: {e}") from e
            return asset, pdf_path

        from desktop.workers import BaseWorker
        class CustomDocWorker(BaseWorker):
            def do_work(self):
                return do_gen()

        self.doc_worker = CustomDocWorker(self.app_context.service_container)
        def on_done(res):
            self.gen_btn.setEnabled(True)
            self.gen_btn.setText("Generate Document Artifact")
            asset, pdf_p = res
            msg = f"### Generated Document Artifact: {asset.title}\n- **Markdown**: `{asset.relative_path}`"
            if pdf_p:
                msg += f"\n- **PDF Artifact**: `{pdf_p.name}`"
            self.add_message("Studio", msg, is_user=False)
            self.load_recent_artifacts()
            QMessageBox.information(self, "Artifact Created", f"Successfully generated:\n{asset.title}")

        def on_err(err):
            self.gen_btn.setEnabled(True)
            self.gen_btn.setText("Generate Document Artifact")
            QMessageBox.critical(self, "Generation Error", f"Failed: {err}")

        self.doc_worker.finished.connect(on_done)
        self.doc_worker.error.connect(on_err)
        self.doc_worker.start()

    def populate_datasets(self):
        vault = self.app_context.service_container.vault
        if not vault:
            return
        self.chart_file_combo.clear()
        for root, _, files in os.walk(vault.root_path):
            if any(p in root for p in [".git", ".venv", ".contextvault", str(vault.generated_dir)]):
                continue
            for f in files:
                if f.lower().endswith((".csv", ".tsv", ".xlsx")):
                    rel = os.path.relpath(os.path.join(root, f), vault.root_path).replace("\\", "/")
                    if vault.is_in_scope(rel, self.get_current_subfolder()):
                        self.chart_file_combo.addItem(rel)

    def on_chart_dataset_selected(self, index):
        vault = self.app_context.service_container.vault
        if not vault or self.chart_file_combo.count() == 0:
            return
        rel = self.chart_file_combo.currentText()
        fpath = vault.root_path / rel
        if fpath.exists():
            try:
                info = ChartGenerator.inspect_dataset(vault, rel)
                cols = info.get("columns", [])
                self.chart_x_combo.clear()
                self.chart_y_combo.clear()
                self.chart_x_combo.addItems(cols)
                self.chart_y_combo.addItems(cols)
                if len(cols) > 1:
                    self.chart_y_combo.setCurrentIndex(1)
            except Exception:
                pass

    def plot_visual_chart(self):
        vault = self.app_context.service_container.vault
        if not vault or self.chart_file_combo.count() == 0:
            QMessageBox.warning(self, "No Dataset", "Please select a CSV or Excel dataset.")
            return

        rel = self.chart_file_combo.currentText()
        fpath = vault.root_path / rel
        ctype = self.chart_type_combo.currentText().lower().split()[0]
        x_col = self.chart_x_combo.currentText()
        y_col = self.chart_y_combo.currentText()

        try:
            chart_info = ChartGenerator.generate_chart(
                chart_type=ctype,
                relative_path=rel,
                x_column=x_col,
                y_column=y_col,
                vault=vault,
                title=f"{x_col} vs {y_col}"
            )
            chart_path = chart_info["image_relative_path"]
            msg = f"### Generated Visual Chart: {chart_info['title']}\n- **Scope**: `{self.get_current_subfolder() or 'Entire Vault'}`\n- **Type**: `{ctype}`\n- **X**: `{x_col}` | **Y**: `{y_col}`\n- **Saved to**: `{chart_path}`"
            self.add_message("Studio", msg, is_user=False)
            self.load_recent_artifacts()
            QMessageBox.information(self, "Chart Plotted", f"Chart saved:\n{chart_path}")
        except Exception as e:
            QMessageBox.critical(self, "Chart Error", f"Failed to plot chart: {e}")

    def load_recent_artifacts(self):
        vault = self.app_context.service_container.vault
        if not vault:
            return
        self.artifacts_list.clear()
        gen_dir = vault.generated_dir
        if gen_dir.exists():
            for root, _, files in os.walk(gen_dir):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), vault.root_path).replace("\\", "/")
                    self.artifacts_list.addItem(rel)

    def open_recent_artifact(self, item: QListWidgetItem):
        vault = self.app_context.service_container.vault
        if not vault:
            return
        rel = item.text()
        abs_p = vault.root_path / rel
        if abs_p.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(abs_p)))
