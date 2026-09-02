"""Small preference dialogs kept separate from the main calculator window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QDoubleSpinBox,
    QComboBox,
    QPushButton,
)

from ..config.constants import SUPPORTED_MODELS
from ..config.settings import AppSettings
from ..database.database import Database
from ..services.settings_service import SettingsService


class SettingsDialog(QDialog):
    """Edit model/API preferences and the local machine profiles."""

    def __init__(self, database: Database, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.database = database
        self.settings_service = SettingsService(database)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumSize(720, 620)

        layout = QVBoxLayout(self)
        api_group = QGroupBox("OpenAI")
        api_form = QFormLayout(api_group)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("Leave blank to keep the saved key")
        api_form.addRow("API key", self.api_key)
        env_key = QLabel("OPENAI_API_KEY is available in the environment." if self._environment_key_available() else "No environment API key detected.")
        env_key.setObjectName("hint")
        api_form.addRow("", env_key)
        clear_key = QPushButton("Clear saved key")
        clear_key.clicked.connect(self._clear_key)
        api_form.addRow("", clear_key)
        layout.addWidget(api_group)

        model_group = QGroupBox("Calculation engine")
        model_form = QFormLayout(model_group)
        self.model = QComboBox()
        self.model.addItems(list(SUPPORTED_MODELS))
        self.model.setCurrentText(settings.model)
        self.reasoning = QComboBox()
        self.reasoning.addItems(["low", "medium", "high"])
        self.reasoning.setCurrentText(settings.reasoning_effort)
        self.mock_mode = QCheckBox("Development/mock mode (results are visibly marked and never cached)")
        self.mock_mode.setChecked(settings.mock_mode)
        model_form.addRow("Model", self.model)
        model_form.addRow("Reasoning effort", self.reasoning)
        model_form.addRow("", self.mock_mode)
        layout.addWidget(model_group)

        machine_group = QGroupBox("Machine profiles")
        machine_layout = QVBoxLayout(machine_group)
        machine_layout.addWidget(QLabel("Edit limits used for local sanity checks. The HAAS VF-9 starts at 10,000 RPM."))
        self.profile_table = QTableWidget(0, 4)
        self.profile_table.setHorizontalHeaderLabels(["Machine", "Max RPM", "Max feed mm/min", "Rigidity"])
        self.profile_table.horizontalHeader().setStretchLastSection(True)
        self.profile_table.setAlternatingRowColors(True)
        self._populate_profiles()
        machine_layout.addWidget(self.profile_table)
        layout.addWidget(machine_group, 1)

        data_label = QLabel(f"Local data: {Path(database.path)}")
        data_label.setObjectName("hint")
        layout.addWidget(data_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _environment_key_available(self) -> bool:
        import os

        return bool(os.environ.get("OPENAI_API_KEY", "").strip())

    def _clear_key(self) -> None:
        self.api_key.clear()
        self.api_key.setPlaceholderText("Saved key will be cleared when you save")
        self._clear_requested = True

    def _populate_profiles(self) -> None:
        self._clear_requested = False
        profiles = self.database.machine_profiles()
        self.profile_table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            name = QTableWidgetItem(profile["name"])
            name.setFlags(name.flags() & ~Qt.ItemIsEditable)
            self.profile_table.setItem(row, 0, name)
            self.profile_table.setItem(row, 1, QTableWidgetItem(f"{profile['max_rpm']:g}"))
            self.profile_table.setItem(row, 2, QTableWidgetItem(f"{profile['max_feed_mm_min']:g}"))
            self.profile_table.setItem(row, 3, QTableWidgetItem(profile["rigidity"]))

    def _save(self) -> None:
        try:
            for row in range(self.profile_table.rowCount()):
                name = self.profile_table.item(row, 0).text()
                max_rpm = float(self.profile_table.item(row, 1).text())
                max_feed = float(self.profile_table.item(row, 2).text())
                rigidity = self.profile_table.item(row, 3).text().strip() or "medium"
                if max_rpm <= 0 or max_feed <= 0:
                    raise ValueError("Machine limits must be greater than zero")
                self.database.update_machine_profile(
                    name,
                    {"max_rpm": max_rpm, "max_feed_mm_min": max_feed, "rigidity": rigidity},
                )
        except (AttributeError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Check machine profiles", str(exc))
            return

        self.settings.model = self.model.currentText()
        self.settings.reasoning_effort = self.reasoning.currentText()
        self.settings.mock_mode = self.mock_mode.isChecked()
        self.settings_service.save(self.settings)
        if getattr(self, "_clear_requested", False):
            self.settings_service.save_api_key("")
        elif self.api_key.text().strip():
            self.settings_service.save_api_key(self.api_key.text())
        self.accept()

