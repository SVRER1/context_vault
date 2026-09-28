import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QListWidget, QLabel, QPushButton, 
    QStatusBar, QFrame, QListWidgetItem, QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt, QSize
from contextvault.services.service_container import ServiceContainer
from desktop.workers import IndexWorker


from desktop.pages.welcome_page import WelcomePage
from desktop.pages.chat_page import ChatPage
from desktop.pages.search_page import SearchPage
from desktop.pages.organise_page import OrganisePage
from desktop.pages.duplicates_page import DuplicatesPage
from desktop.pages.audit_page import AuditPage
from desktop.pages.settings_page import SettingsPage


class AppContext:
    def __init__(self):
        self.service_container = ServiceContainer()
        self.active_vault_path = None
        self.active_subfolder = None


class ContextVaultApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Context Vault")
        self.resize(1240, 820)
        
        
        self.setStyleSheet("""
            QWidget {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            }
            QLabel {
                color: #f1f5f9;
            }
            QComboBox, QLineEdit, QSpinBox {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 5px 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #1e293b;
                color: #f8fafc;
                selection-background-color: #0284c7;
            }
            QTableWidget, QTreeWidget {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #334155;
                gridline-color: #1e293b;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: bold;
                border: 1px solid #334155;
                padding: 6px;
            }
            QStatusBar {
                background-color: #0f172a;
                color: #94a3b8;
                border-top: 1px solid #1e293b;
            }
        """)
        
        self.app_context = AppContext()
        self.index_worker = None
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        
        self.stacked_widget = QStackedWidget()
        
        
        self.welcome_page = WelcomePage(self.app_context)
        self.welcome_page.vault_selected.connect(self.open_vault)
        
        self.stacked_widget.addWidget(self.welcome_page)
        self.main_layout.addWidget(self.stacked_widget)
        
        
        self.vault_ui_container = QWidget()
        self.vault_layout = QHBoxLayout(self.vault_ui_container)
        self.vault_layout.setContentsMargins(0, 0, 0, 0)
        self.vault_layout.setSpacing(0)
        
        self.setup_sidebar()
        self.setup_content_area()
        
        self.vault_layout.addWidget(self.sidebar_widget)
        self.vault_layout.addWidget(self.content_stacked_widget)
        
        self.stacked_widget.addWidget(self.vault_ui_container)
        
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.vault_info_label = QLabel("No Vault Loaded")
        self.llm_status_label = QLabel("LLM: Checking...")
        self.status_bar.addPermanentWidget(self.vault_info_label)
        self.status_bar.addPermanentWidget(self.llm_status_label)
        
        
        self.show_welcome_screen()

    def setup_sidebar(self):
        self.sidebar_widget = QFrame()
        self.sidebar_widget.setFixedWidth(240)
        self.sidebar_widget.setStyleSheet("background-color: #1e293b; color: white;")
        
        sidebar_layout = QVBoxLayout(self.sidebar_widget)
        sidebar_layout.setContentsMargins(12, 20, 12, 20)
        
        
        self.sidebar_vault_name = QLabel("Vault Name")
        font = self.sidebar_vault_name.font()
        font.setBold(True)
        font.setPointSize(12)
        self.sidebar_vault_name.setFont(font)
        
        self.sidebar_vault_path = QLabel("/path/to/vault")
        self.sidebar_vault_path.setStyleSheet("color: #94a3b8; font-size: 10px;")
        
        self.sidebar_file_count = QLabel("0 files (filesystem retrieval ready)")
        self.sidebar_file_count.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        
        
        header_btns = QVBoxLayout()
        header_btns.setSpacing(6)
        
        
        self.index_vault_btn = QPushButton("Scan and Prepare Vault")
        self.index_vault_btn.setStyleSheet("background-color: #0284c7; color: white; padding: 7px; font-weight: bold; border-radius: 4px;")
        self.index_vault_btn.clicked.connect(self.start_indexing)
        
        self.index_progress_bar = QProgressBar()
        self.index_progress_bar.setFixedHeight(12)
        self.index_progress_bar.setTextVisible(False)
        self.index_progress_bar.setVisible(False)
        
        self.index_status_label = QLabel("")
        self.index_status_label.setStyleSheet("color: #38bdf8; font-size: 10px; font-style: italic;")
        self.index_status_label.setVisible(False)
        
        self.change_vault_btn = QPushButton("Change Vault")
        self.change_vault_btn.setStyleSheet("background-color: #334155; color: #e2e8f0; padding: 5px; border-radius: 4px;")
        self.change_vault_btn.clicked.connect(self.show_welcome_screen)
        
        header_btns.addWidget(self.index_vault_btn)
        header_btns.addWidget(self.index_progress_bar)
        header_btns.addWidget(self.index_status_label)
        header_btns.addWidget(self.change_vault_btn)
        
        sidebar_layout.addWidget(self.sidebar_vault_name)
        sidebar_layout.addWidget(self.sidebar_vault_path)
        sidebar_layout.addWidget(self.sidebar_file_count)
        sidebar_layout.addSpacing(6)
        sidebar_layout.addLayout(header_btns)
        sidebar_layout.addSpacing(16)
        
        
        self.nav_list = QListWidget()
        self.nav_list.setStyleSheet("""
            QListWidget {
                border: none;
                background-color: transparent;
            }
            QListWidget::item {
                padding: 10px;
                color: #e2e8f0;
                border-radius: 6px;
            }
            QListWidget::item:selected {
                background-color: #0284c7;
                color: white;
                font-weight: bold;
            }
            QListWidget::item:hover:!selected {
                background-color: #334155;
            }
        """)
        
        nav_items = ["Chat & Studio", "Search", "Organise", "Duplicates", "Audit", "Settings"]
        for item_text in nav_items:
            item = QListWidgetItem(item_text)
            item.setSizeHint(QSize(0, 38))
            self.nav_list.addItem(item)
            
        self.nav_list.currentRowChanged.connect(self.change_page)
        sidebar_layout.addWidget(self.nav_list)
        sidebar_layout.addStretch()

    def setup_content_area(self):
        self.content_stacked_widget = QStackedWidget()
        
        from desktop.pages.generate_page import GeneratePage
        self.pages = {
            "Chat & Studio": ChatPage(self.app_context),
            "Search": SearchPage(self.app_context),
            "Organise": OrganisePage(self.app_context),
            "Duplicates": DuplicatesPage(self.app_context),
            "Generate": GeneratePage(self.app_context),
            "Audit": AuditPage(self.app_context),
            "Settings": SettingsPage(self.app_context)
        }
        
        for page in self.pages.values():
            self.content_stacked_widget.addWidget(page)

    def show_welcome_screen(self):
        self.welcome_page.load_recent()
        self.stacked_widget.setCurrentWidget(self.welcome_page)
        self.status_bar.hide()
        self.app_context.active_vault_path = None
        self.app_context.active_subfolder = None

    def open_vault(self, path):
        self.app_context.active_vault_path = path
        self.app_context.active_subfolder = None
        
        
        try:
            self.app_context.service_container.open_vault(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not open vault: {e}")
            return
            
        self.update_vault_info()
        
        self.stacked_widget.setCurrentWidget(self.vault_ui_container)
        self.status_bar.show()
        
        
        self.nav_list.setCurrentRow(0)
        self.change_page(0)

    def start_indexing(self):
        """Run full indexing pipeline in background thread."""
        vault = self.app_context.service_container.vault
        if not vault:
            return

        self.index_vault_btn.setEnabled(False)
        self.index_progress_bar.setVisible(True)
        self.index_progress_bar.setValue(0)
        self.index_status_label.setVisible(True)
        self.index_status_label.setText("Scanning vault files...")

        self.index_worker = IndexWorker(self.app_context.service_container)
        self.index_worker.progress.connect(self.handle_index_progress)
        self.index_worker.finished.connect(self.handle_index_finished)
        self.index_worker.error.connect(self.handle_index_error)
        self.index_worker.start()

    def handle_index_progress(self, cur, tot, msg):
        self.index_progress_bar.setValue(cur)
        self.index_status_label.setText(msg)

    def handle_index_finished(self, stats):
        self.index_vault_btn.setEnabled(True)
        self.index_progress_bar.setVisible(False)
        self.index_status_label.setText("Vault preparation complete!")
        self.update_vault_info()
        QMessageBox.information(
            self, "Indexing Complete",
            f"Vault prepared:\n- Files Parsed: {stats.get('parsed_files', stats.get('parsed', 0))}\n- Cached Passages: {stats.get('total_chunks', stats.get('chunks_created', 0))}"
        )

    def handle_index_error(self, err_msg):
        self.index_vault_btn.setEnabled(True)
        self.index_progress_bar.setVisible(False)
        self.index_status_label.setText("Indexing Failed")
        QMessageBox.critical(self, "Indexing Error", f"Failed to index vault:\n{err_msg}")

    def update_vault_info(self):
        vault = self.app_context.service_container.vault
        if not vault:
            return

        name = vault.display_name
        path_str = str(vault.root_path)
        
        self.sidebar_vault_name.setText(name)
        self.sidebar_vault_path.setText(path_str)
        
        
        info = self.app_context.service_container.vault_service.get_vault_status(vault)
        f_count = info.get("file_count", 0)
        c_count = info.get("chunk_count", 0)
        
        self.sidebar_file_count.setText(f"{f_count} files (filesystem retrieval ready; {c_count} cached passages)")
        self.vault_info_label.setText(f"Vault: {name} ({f_count} files)")
        
        
        
        if self.app_context.service_container.has_llm:
            self.llm_status_label.setText("Artifact provider: Available")
            self.llm_status_label.setStyleSheet("color: #10b981;")
        else:
            self.llm_status_label.setText("Artifact provider: Optional (not checked)")
            self.llm_status_label.setStyleSheet("color: #94a3b8;")

    def change_page(self, index):
        if 0 <= index < self.nav_list.count():
            page_name = self.nav_list.item(index).text()
            page = self.pages.get(page_name)
            if page is not None:
                self.content_stacked_widget.setCurrentWidget(page)
