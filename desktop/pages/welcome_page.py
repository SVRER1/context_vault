import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, 
                               QFileDialog, QListWidget, QMessageBox)
from PySide6.QtCore import Signal, Qt

class WelcomePage(QWidget):
    vault_selected = Signal(str)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
                    
        title = QLabel("Context Vault")
        font = title.font()
        font.setPointSize(24)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
                  
        subtitle = QLabel("Turn a folder into an intelligent knowledge workspace")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        
        layout.addSpacing(20)
        
                              
        self.select_btn = QPushButton("Select Folder")
        self.select_btn.setMinimumWidth(200)
        self.select_btn.clicked.connect(self.select_folder)
        layout.addWidget(self.select_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        layout.addSpacing(30)
        
                       
        recent_label = QLabel("Recent Vaults:")
        layout.addWidget(recent_label)
        
        self.recent_list = QListWidget()
        self.recent_list.setMaximumWidth(400)
        self.recent_list.itemClicked.connect(self.recent_selected)
        layout.addWidget(self.recent_list, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.load_recent()
        
    def load_recent(self):
        try:
            self.recent_list.clear()
            vaults = self.app_context.service_container.vault_service.list_vaults()
            for v in vaults:
                self.recent_list.addItem(v.absolute_path)
        except Exception:
            pass

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Vault Folder")
        if folder:
            self.vault_selected.emit(folder)
            
    def recent_selected(self, item):
        folder = item.text()
        if os.path.exists(folder):
            self.vault_selected.emit(folder)
        else:
            QMessageBox.warning(self, "Error", "Folder does not exist anymore.")
