"""AI Models Settings UI - Model discovery, selection, and testing."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pactlyn.app.bootstrap import AppContainer
from pactlyn.llm.discovery import OllamaDiscoveryService, ModelCapabilities, CapabilityState
from pactlyn.llm.model_config import ModelConfigurationService, ModelRole, is_model_compatible_for_role
from pactlyn.ui.theme import ThemeMode, status_color


class ModelDiscoveryWorker(QThread):
    """Background worker for Ollama model discovery."""
    
    finished = Signal(object)  # Emits dict with models and metadata
    failed = Signal(str)  # Emits error message
    
    def __init__(self, ollama_url: str) -> None:
        super().__init__()
        self.ollama_url = ollama_url
    
    def run(self) -> None:
        try:
            discovery = OllamaDiscoveryService(self.ollama_url)
            inventory = asyncio.run(discovery.discover_models())
            
            # Classify capabilities for each model
            async def classify_all():
                models_dict = {}
                for model_detail in inventory.models:
                    caps = await discovery.classify_capabilities(model_detail)
                    models_dict[model_detail.name + ":" + model_detail.tag] = caps
                return models_dict
            
            models_dict = asyncio.run(classify_all())
            
            result = {
                "connection_ok": inventory.connection.is_connected,
                "ollama_version": inventory.connection.ollama_version,
                "models": models_dict,
                "last_checked": inventory.discovered_at
            }
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(f"Discovery failed: {exc}")


class ModelTestWorker(QThread):
    """Background worker for testing model capabilities."""
    
    finished = Signal(str)  # Emits success message
    failed = Signal(str)  # Emits error message
    
    def __init__(
        self,
        ollama_url: str,
        model_name: str,
        test_type: str,  # "text", "embedding", or "vision"
    ) -> None:
        super().__init__()
        self.ollama_url = ollama_url
        self.model_name = model_name
        self.test_type = test_type
    
    def run(self) -> None:
        try:
            discovery = OllamaDiscoveryService(self.ollama_url)
            
            if self.test_type == "text":
                result = asyncio.run(discovery.verify_text_generation_capability(self.model_name))
                if result:
                    self.finished.emit(f"✓ {self.model_name} successfully generated text")
                else:
                    self.failed.emit(f"✗ {self.model_name} failed text generation test")
            
            elif self.test_type == "embedding":
                is_valid, dimension = asyncio.run(discovery.verify_embedding_capability(self.model_name))
                if is_valid:
                    self.finished.emit(f"✓ {self.model_name} generated {dimension}-dimensional embeddings")
                else:
                    self.failed.emit(f"✗ {self.model_name} failed embedding test")
            
            elif self.test_type == "vision":
                self.failed.emit("Vision model testing not yet implemented")
            
            else:
                self.failed.emit(f"Unknown test type: {self.test_type}")
        
        except Exception as exc:
            self.failed.emit(f"Test failed: {exc}")


class ModelSelectionDialog(QDialog):
    """Dialog showing model details and selection confirmation."""
    
    def __init__(
        self,
        parent: QWidget | None,
        model_name: str,
        role: str,
        capabilities: ModelCapabilities,
    ) -> None:
        super().__init__(parent)
        self.model_name = model_name
        self.role = role
        self.capabilities = capabilities
        
        self.setWindowTitle(f"Select {role.capitalize()} Model")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        
        # Model info
        info_group = QGroupBox("Model Information")
        info_layout = QFormLayout()
        
        info_layout.addRow("Model:", QLabel(model_name))
        info_layout.addRow("Role:", QLabel(role.capitalize()))
        
        if capabilities.model_type:
            info_layout.addRow("Type:", QLabel(capabilities.model_type))
        if capabilities.parameter_count:
            info_layout.addRow("Parameters:", QLabel(capabilities.parameter_count))
        if capabilities.quantization:
            info_layout.addRow("Quantization:", QLabel(capabilities.quantization))
        if capabilities.context_length:
            info_layout.addRow("Context:", QLabel(f"{capabilities.context_length:,} tokens"))
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Capabilities
        cap_group = QGroupBox("Capabilities")
        cap_layout = QFormLayout()
        
        cap_layout.addRow("Text Generation:", QLabel(self._cap_status(capabilities.text_generation)))
        cap_layout.addRow("Embeddings:", QLabel(self._cap_status(capabilities.embedding)))
        cap_layout.addRow("Vision:", QLabel(self._cap_status(capabilities.vision_language)))
        
        if capabilities.embedding_dimension:
            cap_layout.addRow("Embedding Dim:", QLabel(str(capabilities.embedding_dimension)))
        
        cap_group.setLayout(cap_layout)
        layout.addWidget(cap_group)
        
        # Warning if role mismatch
        is_compatible, reason = is_model_compatible_for_role(capabilities, role)
        if not is_compatible:
            warning = QLabel(f"⚠ Warning: {reason}")
            warning.setStyleSheet("color: orange;")
            layout.addWidget(warning)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _cap_status(self, state: CapabilityState) -> str:
        if state == CapabilityState.SUPPORTED:
            return "✓ Supported"
        elif state == CapabilityState.LIKELY:
            return "? Likely"
        elif state == CapabilityState.UNSUPPORTED:
            return "✗ Not supported"
        return "? Unknown"


class AIModelsSettingsPage(QWidget):
    """Settings page for AI model discovery, selection, and testing."""
    
    modelChanged = Signal()  # Emitted when model selection changes
    
    def __init__(self, container: AppContainer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self.discovered_models: dict[str, ModelCapabilities] = {}
        self.discovery_worker: ModelDiscoveryWorker | None = None
        self.test_worker: ModelTestWorker | None = None
        
        self._build_ui()
        self.refresh()
    
    def set_theme(self, mode: ThemeMode) -> None:
        """Apply theme to this page."""
        # Theme is handled at application level
        pass
    
    def _build_ui(self) -> None:
        """Build the AI Models settings interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(20)
        
        # === Ollama Connection Section ===
        conn_group = QGroupBox("Ollama Connection")
        conn_layout = QFormLayout()
        conn_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        self.server_url_label = QLabel(self.container.settings.ollama_url)
        conn_layout.addRow("Server URL:", self.server_url_label)
        
        self.connection_status_label = QLabel("Unknown")
        conn_layout.addRow("Status:", self.connection_status_label)
        
        self.ollama_version_label = QLabel("—")
        conn_layout.addRow("Ollama Version:", self.ollama_version_label)
        
        self.model_count_label = QLabel("—")
        conn_layout.addRow("Installed Models:", self.model_count_label)
        
        self.last_discovery_label = QLabel("Never")
        conn_layout.addRow("Last Discovery:", self.last_discovery_label)
        
        refresh_btn = QPushButton("Refresh Models")
        refresh_btn.clicked.connect(self._discover_models)
        conn_layout.addRow("", refresh_btn)
        
        conn_group.setLayout(conn_layout)
        content_layout.addWidget(conn_group)
        
        # === Model Selection Section ===
        selection_group = QGroupBox("Model Selection")
        selection_layout = QFormLayout()
        selection_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        # Assistant model
        assistant_layout = QHBoxLayout()
        self.assistant_combo = QComboBox()
        self.assistant_combo.setMinimumWidth(300)
        assistant_layout.addWidget(self.assistant_combo, 1)
        
        test_assistant_btn = QPushButton("Test")
        test_assistant_btn.clicked.connect(lambda: self._test_model(ModelRole.ASSISTANT))
        assistant_layout.addWidget(test_assistant_btn)
        
        selection_layout.addRow("Assistant Model:", assistant_layout)
        
        # Embedding model
        embedding_layout = QHBoxLayout()
        self.embedding_combo = QComboBox()
        self.embedding_combo.setMinimumWidth(300)
        embedding_layout.addWidget(self.embedding_combo, 1)
        
        test_embedding_btn = QPushButton("Test")
        test_embedding_btn.clicked.connect(lambda: self._test_model(ModelRole.EMBEDDING))
        embedding_layout.addWidget(test_embedding_btn)
        
        selection_layout.addRow("Embedding Model:", embedding_layout)
        
        # Save button
        save_btn = QPushButton("Save Model Selection")
        save_btn.clicked.connect(self._save_selection)
        save_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        selection_layout.addRow("", save_btn)
        
        selection_group.setLayout(selection_layout)
        content_layout.addWidget(selection_group)
        
        # === Model Inventory Section ===
        inventory_group = QGroupBox("Installed Models")
        inventory_layout = QVBoxLayout()
        
        self.inventory_text = QTextEdit()
        self.inventory_text.setReadOnly(True)
        self.inventory_text.setMaximumHeight(300)
        inventory_layout.addWidget(self.inventory_text)
        
        inventory_group.setLayout(inventory_layout)
        content_layout.addWidget(inventory_group)
        
        # === Status Section ===
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 10px; background-color: #f0f0f0; border-radius: 4px;")
        content_layout.addWidget(self.status_label)
        
        content_layout.addStretch()
        
        scroll.setWidget(content)
        layout.addWidget(scroll)
    
    def refresh(self) -> None:
        """Refresh the page with current data."""
        session = self.container.session()
        try:
            config_service = ModelConfigurationService(session)
            active = config_service.get_all_active_models()
            
            # Update connection status
            self._update_connection_status("Checking...")
            
            # Load saved selections
            if active.assistant_model:
                self._select_model_in_combo(self.assistant_combo, active.assistant_model)
            if active.embedding_model:
                self._select_model_in_combo(self.embedding_combo, active.embedding_model)
            
            self._set_status("Ready. Click 'Refresh Models' to discover installed models.", "info")
        finally:
            session.close()
    
    def _discover_models(self) -> None:
        """Start background model discovery."""
        if self.discovery_worker and self.discovery_worker.isRunning():
            self._set_status("Discovery already in progress...", "warning")
            return
        
        self._set_status("Discovering models...", "info")
        self._update_connection_status("Discovering...")
        
        self.discovery_worker = ModelDiscoveryWorker(self.container.settings.ollama_url)
        self.discovery_worker.finished.connect(self._discovery_finished)
        self.discovery_worker.failed.connect(self._discovery_failed)
        self.discovery_worker.start()
    
    def _discovery_finished(self, result: dict[str, Any]) -> None:
        """Handle successful model discovery."""
        self.discovered_models = result.get("models", {})
        connection_ok = result.get("connection_ok", False)
        ollama_version = result.get("ollama_version")
        
        if connection_ok:
            self._update_connection_status("Connected", "success")
        else:
            self._update_connection_status("Failed", "error")
        
        if ollama_version:
            self.ollama_version_label.setText(ollama_version)
        
        self.model_count_label.setText(str(len(self.discovered_models)))
        self.last_discovery_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        # Update model dropdowns
        self._populate_model_combos()
        
        # Update inventory display
        self._update_inventory_display()
        
        self._set_status(f"Discovered {len(self.discovered_models)} models", "success")
    
    def _discovery_failed(self, error: str) -> None:
        """Handle failed model discovery."""
        self._update_connection_status("Failed", "error")
        self._set_status(f"Discovery failed: {error}", "error")
        
        QMessageBox.warning(
            self,
            "Discovery Failed",
            f"Failed to discover Ollama models:\n\n{error}\n\nPlease check that Ollama is running."
        )
    
    def _populate_model_combos(self) -> None:
        """Populate model selection dropdowns with compatible models."""
        session = self.container.session()
        try:
            config_service = ModelConfigurationService(session)
            active = config_service.get_all_active_models()
            
            # Clear existing items
            self.assistant_combo.clear()
            self.embedding_combo.clear()
            
            # Populate assistant models (text generation capable)
            assistant_models = [
                name for name, caps in self.discovered_models.items()
                if is_model_compatible_for_role(caps, ModelRole.ASSISTANT)[0]
            ]
            self.assistant_combo.addItems(sorted(assistant_models))
            if active.assistant_model:
                self._select_model_in_combo(self.assistant_combo, active.assistant_model)
            
            # Populate embedding models
            embedding_models = [
                name for name, caps in self.discovered_models.items()
                if is_model_compatible_for_role(caps, ModelRole.EMBEDDING)[0]
            ]
            self.embedding_combo.addItems(sorted(embedding_models))
            if active.embedding_model:
                self._select_model_in_combo(self.embedding_combo, active.embedding_model)
        
        finally:
            session.close()
    
    def _select_model_in_combo(self, combo: QComboBox, model_name: str) -> None:
        """Select a model in a combo box by name."""
        index = combo.findText(model_name)
        if index >= 0:
            combo.setCurrentIndex(index)
    
    def _update_inventory_display(self) -> None:
        """Update the model inventory text display."""
        if not self.discovered_models:
            self.inventory_text.setPlainText("No models discovered. Click 'Refresh Models' to scan.")
            return
        
        lines = []
        for model_name, caps in sorted(self.discovered_models.items()):
            lines.append(f"━━━ {model_name} ━━━")
            
            if caps.model_type:
                lines.append(f"  Type: {caps.model_type}")
            if caps.parameter_count:
                lines.append(f"  Parameters: {caps.parameter_count}")
            if caps.quantization:
                lines.append(f"  Quantization: {caps.quantization}")
            if caps.context_length:
                lines.append(f"  Context: {caps.context_length:,} tokens")
            
            # Capabilities
            capabilities_list = []
            if caps.text_generation == CapabilityState.SUPPORTED:
                capabilities_list.append("Text Generation")
            if caps.embedding == CapabilityState.SUPPORTED:
                capabilities_list.append("Embeddings")
            if caps.vision_language == CapabilityState.SUPPORTED:
                capabilities_list.append("Vision")
            
            if capabilities_list:
                lines.append(f"  Capabilities: {', '.join(capabilities_list)}")
            
            if caps.embedding_dimension:
                lines.append(f"  Embedding Dimension: {caps.embedding_dimension}")
            
            lines.append("")  # Blank line between models
        
        self.inventory_text.setPlainText("\n".join(lines))
    
    def _save_selection(self) -> None:
        """Save the selected models to database."""
        assistant_model = self.assistant_combo.currentText()
        embedding_model = self.embedding_combo.currentText()
        
        if not assistant_model or not embedding_model:
            QMessageBox.warning(
                self,
                "Incomplete Selection",
                "Please select both an assistant model and an embedding model."
            )
            return
        
        # Check embedding dimension compatibility
        if embedding_model in self.discovered_models:
            caps = self.discovered_models[embedding_model]
            if caps.embedding_dimension:
                # TODO: Check against existing Qdrant collection dimension
                # For now, just warn if changing embedding model
                session = self.container.session()
                try:
                    config_service = ModelConfigurationService(session)
                    active = config_service.get_all_active_models()
                    
                    if active.embedding_model and active.embedding_model != embedding_model:
                        reply = QMessageBox.warning(
                            self,
                            "Embedding Model Change",
                            f"Changing the embedding model from '{active.embedding_model}' to '{embedding_model}' "
                            "may require reindexing your memory vectors.\n\n"
                            "Continue with this change?",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No
                        )
                        if reply != QMessageBox.Yes:
                            return
                finally:
                    session.close()
        
        # Save selections
        session = self.container.session()
        try:
            config_service = ModelConfigurationService(session)
            
            config_service.set_active_model(ModelRole.ASSISTANT, assistant_model)
            config_service.set_active_model(ModelRole.EMBEDDING, embedding_model)
            
            session.commit()
            
            self._set_status(
                f"✓ Saved: {assistant_model} (assistant), {embedding_model} (embedding). "
                "Restart Pactlyn for changes to take effect.",
                "success"
            )
            
            QMessageBox.information(
                self,
                "Models Saved",
                f"Model selection saved successfully.\n\n"
                f"Assistant: {assistant_model}\n"
                f"Embedding: {embedding_model}\n\n"
                "Please restart Pactlyn for the changes to take effect."
            )
            
            self.modelChanged.emit()
        
        except Exception as exc:
            self._set_status(f"Failed to save: {exc}", "error")
            QMessageBox.critical(
                self,
                "Save Failed",
                f"Failed to save model selection:\n\n{exc}"
            )
        finally:
            session.close()
    
    def _test_model(self, role: str) -> None:
        """Test the currently selected model for a role."""
        if role == ModelRole.ASSISTANT:
            model_name = self.assistant_combo.currentText()
            test_type = "text"
        elif role == ModelRole.EMBEDDING:
            model_name = self.embedding_combo.currentText()
            test_type = "embedding"
        else:
            return
        
        if not model_name:
            QMessageBox.warning(self, "No Model", f"Please select a {role} model first.")
            return
        
        if self.test_worker and self.test_worker.isRunning():
            QMessageBox.warning(self, "Test Running", "A model test is already in progress.")
            return
        
        self._set_status(f"Testing {model_name}...", "info")
        
        self.test_worker = ModelTestWorker(
            self.container.settings.ollama_url,
            model_name,
            test_type
        )
        self.test_worker.finished.connect(self._test_finished)
        self.test_worker.failed.connect(self._test_failed)
        self.test_worker.start()
    
    def _test_finished(self, message: str) -> None:
        """Handle successful model test."""
        self._set_status(message, "success")
        QMessageBox.information(self, "Test Successful", message)
    
    def _test_failed(self, error: str) -> None:
        """Handle failed model test."""
        self._set_status(error, "error")
        QMessageBox.warning(self, "Test Failed", error)
    
    def _update_connection_status(self, status: str, level: str = "info") -> None:
        """Update the connection status label."""
        color = status_color(level)
        self.connection_status_label.setText(status)
        self.connection_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
    
    def _set_status(self, message: str, level: str = "info") -> None:
        """Set the status message."""
        color = status_color(level)
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            f"padding: 10px; background-color: {color}20; "
            f"border-left: 4px solid {color}; border-radius: 4px;"
        )
    
    def shutdown(self) -> None:
        """Clean up resources before closing."""
        if self.discovery_worker and self.discovery_worker.isRunning():
            self.discovery_worker.quit()
            self.discovery_worker.wait()
        
        if self.test_worker and self.test_worker.isRunning():
            self.test_worker.quit()
            self.test_worker.wait()
