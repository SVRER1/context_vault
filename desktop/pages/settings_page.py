import requests
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, 
    QSpinBox, QDoubleSpinBox, QComboBox, QPushButton, QMessageBox, QLabel, QHBoxLayout
)

class SettingsPage(QWidget):
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        config = self.app_context.service_container.config

        self.ollama_url = QLineEdit()
        self.ollama_url.setText(config.ollama_base_url)
        form_layout.addRow("Ollama Server URL:", self.ollama_url)
        
        
        model_layout = QHBoxLayout()
        self.llm_model_combo = QComboBox()
        self.llm_model_combo.setEditable(True)
        self.refresh_models_btn = QPushButton("Refresh Models")
        self.refresh_models_btn.clicked.connect(self.populate_installed_models)
        model_layout.addWidget(self.llm_model_combo)
        model_layout.addWidget(self.refresh_models_btn)
        form_layout.addRow("LLM Model:", model_layout)
        
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 1.0)
        self.temperature_spin.setSingleStep(0.05)
        self.temperature_spin.setValue(config.temperature)
        form_layout.addRow("Temperature:", self.temperature_spin)

        self.retrieval_results = QSpinBox()
        self.retrieval_results.setRange(1, 50)
        self.retrieval_results.setValue(config.retrieval_max_candidates)
        form_layout.addRow("Candidate Files (Top-K):", self.retrieval_results)
        
        self.output_folder = QLineEdit()
        self.output_folder.setText(config.generated_output_folder)
        form_layout.addRow("Generated Output Folder:", self.output_folder)
        
        
        btn_layout = QHBoxLayout()
        self.test_btn = QPushButton("Test Ollama Connection")
        self.test_btn.clicked.connect(self.test_connection)
        btn_layout.addWidget(self.test_btn)
        
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setStyleSheet("font-weight: bold; background-color: #0284c7; color: white; padding: 6px 12px; border-radius: 4px;")
        self.save_btn.clicked.connect(self.save_settings)
        btn_layout.addWidget(self.save_btn)
        
        form_layout.addRow("", btn_layout)
        
        layout.addLayout(form_layout)
        layout.addStretch()

        self.populate_installed_models()

    def populate_installed_models(self):
        url = self.ollama_url.text().strip().rstrip("/")
        current = self.app_context.service_container.config.ollama_model
        
        models = []
        try:
            resp = requests.get(f"{url}/api/tags", timeout=3)
            if resp.status_code == 200:
                data = resp.json().get("models", [])
                models = [m.get("name") for m in data if m.get("name")]
        except Exception:
            pass

        self.llm_model_combo.clear()
        
        
        preferred = "gemma4:e2b"
            
        if models:
            for m in models:
                label = f"{m} (Recommended)" if m.lower() == preferred.lower() else m
                self.llm_model_combo.addItem(label, userData=m)
            
            
            idx = -1
            for i in range(self.llm_model_combo.count()):
                data = self.llm_model_combo.itemData(i)
                if data == current or (not current and data.lower() == preferred.lower()):
                    idx = i
                    break
            if idx >= 0:
                self.llm_model_combo.setCurrentIndex(idx)
            elif preferred:
                self.llm_model_combo.setEditText(preferred)
        else:
            self.llm_model_combo.addItem(current or preferred, userData=current or preferred)

    def test_connection(self):
        url = self.ollama_url.text().strip().rstrip("/")
        model_name = self.llm_model_combo.currentData() or self.llm_model_combo.currentText().strip()
        try:
            resp = requests.get(f"{url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m.get("name") for m in resp.json().get("models", [])]
                has_model = any(model_name.lower() in m.lower() or m.lower() in model_name.lower() for m in models)
                if has_model:
                    QMessageBox.information(
                        self, "Ollama Ready",
                        f"Connected to Ollama at {url}!\nModel '{model_name}' is installed and ready."
                    )
                else:
                    QMessageBox.warning(
                        self, "Model Not Found",
                        f"Connected to Ollama at {url}, but '{model_name}' was not found in installed models:\n{', '.join(models[:5])}"
                    )
            else:
                QMessageBox.warning(self, "Warning", f"Received unexpected status code: {resp.status_code}")
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", f"Could not connect to Ollama at {url}:\n{e}")

    def save_settings(self):
        try:
            config = self.app_context.service_container.config
            config.ollama_base_url = self.ollama_url.text().strip()
            
            selected_model = self.llm_model_combo.currentData() or self.llm_model_combo.currentText().strip()
            
            selected_model = selected_model.replace(" (Recommended)", "").strip()
            config.ollama_model = selected_model
            
            config.temperature = self.temperature_spin.value()
            config.retrieval_max_candidates = self.retrieval_results.value()
            config.generated_output_folder = self.output_folder.text().strip()
            config.save()
            
            
            if hasattr(self.app_context.service_container, "_llm_client"):
                client = self.app_context.service_container._llm_client
                if client:
                    client.base_url = config.ollama_base_url
                    client.model = config.ollama_model
            
            QMessageBox.information(self, "Settings Saved", f"Configuration saved successfully!\nActive model: {config.ollama_model}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")
