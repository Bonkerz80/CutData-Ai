"""Small preference dialogs kept separate from the main calculator window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QComboBox,
    QPushButton,
    QWidget,
)

from ..config.constants import (
    APP_NAME,
    APP_VERSION,
    COMPANY_NAME,
    COMPANY_WEBSITE,
    DEFAULT_MODEL,
    ICON_SVG_PATH,
    PRODUCT_TAGLINE,
    PUBLISHER_NAME,
    REPOSITORY_URL,
    SUPPORTED_MODELS,
    model_display_name,
)
from ..config.settings import AppSettings
from ..database.database import Database
from ..services.openai_service import (
    ConnectionTestResult,
    OpenAIService,
    connection_result_for_exception,
)
from ..services.settings_service import SettingsService
from .widgets import ModeSwitch


class ConnectionTestWorker(QObject):
    """Run a key/model probe away from the settings dialog's UI thread."""

    finished = Signal(object)
    done = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.cancelled = False

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.test_connection()
        except Exception as exc:
            result = connection_result_for_exception(exc, self.service.model)
        if not self.cancelled:
            self.finished.emit(result)
        self.done.emit()

    def cancel(self) -> None:
        self.cancelled = True


class AboutDialog(QDialog):
    """Show product, publisher, version, engine, and repository details."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setWindowIcon(QIcon(str(ICON_SVG_PATH)))
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        brand_row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QIcon(str(ICON_SVG_PATH)).pixmap(68, 68))
        icon.setAccessibleName(f"{PUBLISHER_NAME} mark")
        brand_row.addWidget(icon)
        brand_text = QVBoxLayout()
        publisher = QLabel(PUBLISHER_NAME)
        publisher.setObjectName("publisherBrand")
        product = QLabel(APP_NAME)
        product.setObjectName("appTitle")
        brand_text.addWidget(publisher)
        brand_text.addWidget(product)
        brand_row.addLayout(brand_text)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)

        details = QLabel(
            f"Version {APP_VERSION}<br>"
            f"{PRODUCT_TAGLINE}<br><br>"
            f"Developed by {PUBLISHER_NAME}<br>"
            f"{COMPANY_NAME}<br>"
            f"Default engine: {model_display_name(DEFAULT_MODEL)}<br>"
            f'<a href="{COMPANY_WEBSITE}">{COMPANY_WEBSITE}</a><br>'
            f'<a href="{REPOSITORY_URL}">{REPOSITORY_URL}</a>'
        )
        details.setOpenExternalLinks(True)
        details.setTextInteractionFlags(Qt.TextBrowserInteraction)
        details.setWordWrap(True)
        details.setObjectName("aboutDetails")
        layout.addWidget(details)
        self.details = details

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class SettingsDialog(QDialog):
    """Edit model/API preferences and the local machine profiles."""

    connection_test_finished = Signal(object)

    def __init__(self, database: Database, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.database = database
        self.settings_service = SettingsService(database)
        self.settings = settings
        self._clear_requested = False
        self._connection_thread: QThread | None = None
        self._connection_worker: ConnectionTestWorker | None = None
        self.setWindowTitle("Settings")
        self.setMinimumSize(720, 650)

        layout = QVBoxLayout(self)
        api_group = QGroupBox("OpenAI")
        api_layout = QVBoxLayout(api_group)

        mode_heading = QLabel("DEVELOPMENT / MOCK MODE")
        mode_heading.setObjectName("formHeading")
        api_layout.addWidget(mode_heading)
        mode_row = QWidget()
        mode_row_layout = QHBoxLayout(mode_row)
        mode_row_layout.setContentsMargins(0, 0, 0, 0)
        self.mock_mode = ModeSwitch(settings.mock_mode)
        mode_hint = QLabel("Offline development results are visibly marked and never cached.")
        mode_hint.setObjectName("hint")
        mode_hint.setWordWrap(True)
        mode_row_layout.addWidget(self.mock_mode)
        mode_row_layout.addWidget(mode_hint, 1)
        mode_form = QFormLayout()
        mode_form.addRow("Mode", mode_row)
        api_layout.addLayout(mode_form)

        engine_form = QFormLayout()
        self.model = QComboBox()
        self.model.addItems(list(SUPPORTED_MODELS))
        self.model.setCurrentText(settings.model)
        self.reasoning = QComboBox()
        self.reasoning.addItems(["low", "medium", "high"])
        self.reasoning.setCurrentText(settings.reasoning_effort)
        engine_form.addRow("Model", self.model)
        engine_form.addRow("Reasoning", self.reasoning)
        api_layout.addLayout(engine_form)

        status_heading = QLabel("API STATUS")
        status_heading.setObjectName("formHeading")
        api_layout.addWidget(status_heading)
        status_form = QFormLayout()
        self.saved_key_status = QLabel()
        self.environment_key_status = QLabel()
        self.active_key_source = QLabel()
        for label in (self.saved_key_status, self.environment_key_status, self.active_key_source):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_form.addRow("Saved key", self.saved_key_status)
        status_form.addRow("Environment key", self.environment_key_status)
        status_form.addRow("Active source", self.active_key_source)
        api_layout.addLayout(status_form)
        for value_label in (self.saved_key_status, self.environment_key_status, self.active_key_source):
            value_label.setObjectName("statusValue")
            status_form.labelForField(value_label).setObjectName("statusLabel")

        entry_heading = QLabel("API KEY ENTRY")
        entry_heading.setObjectName("formHeading")
        api_layout.addWidget(entry_heading)
        api_form = QFormLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("Leave blank to keep the currently saved key")
        self.api_key.setToolTip("Keys are stored locally using Windows encryption; the field never shows the saved key.")
        api_form.addRow("API key", self.api_key)
        key_hint = QLabel("Leave blank to keep the currently saved key. OPENAI_API_KEY overrides it when detected.")
        key_hint.setObjectName("hint")
        key_hint.setWordWrap(True)
        api_form.addRow("", key_hint)
        api_layout.addLayout(api_form)

        key_actions = QHBoxLayout()
        self.test_connection_button = QPushButton("TEST CONNECTION")
        self.test_connection_button.setObjectName("secondaryAction")
        self.test_connection_button.clicked.connect(self._test_connection)
        self.clear_key_button = QPushButton("CLEAR SAVED KEY")
        self.clear_key_button.clicked.connect(self._clear_key)
        key_actions.addWidget(self.test_connection_button)
        key_actions.addWidget(self.clear_key_button)
        key_actions.addStretch(1)
        api_layout.addLayout(key_actions)
        self.connection_status = QLabel("Connection not tested.")
        self.connection_status.setObjectName("hint")
        self.connection_status.setWordWrap(True)
        api_layout.addWidget(self.connection_status)
        self.api_key.textChanged.connect(self._key_edited)
        self._refresh_api_status()
        layout.addWidget(api_group)

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

        self.dialog_buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.dialog_buttons.button(QDialogButtonBox.Save).setText("SAVE SETTINGS")
        self.dialog_buttons.accepted.connect(self._save)
        self.dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(self.dialog_buttons)

    def _environment_key_available(self) -> bool:
        return self.settings_service.get_api_key_status().environment_detected

    def _refresh_api_status(self) -> None:
        status = self.settings_service.get_api_key_status()
        self.saved_key_status.setText("Configured" if status.saved_configured else "Not configured")
        self.environment_key_status.setText("Detected" if status.environment_detected else "Not detected")
        self.active_key_source.setText(
            {
                "environment": "OPENAI_API_KEY environment variable",
                "saved": "Windows encrypted saved key",
                "none": "None",
            }[status.source]
        )

    def _clear_key(self) -> None:
        self._clear_requested = True
        self.api_key.clear()
        self.api_key.setPlaceholderText("Saved key will be cleared when you save")
        self.saved_key_status.setText("Not configured after save")

    def _key_edited(self, value: str) -> None:
        if value.strip():
            self._clear_requested = False

    def _candidate_api_key(self) -> str:
        entered = self.api_key.text().strip()
        if entered:
            return entered
        if self._clear_requested:
            return self.settings_service.get_environment_api_key()
        return self.settings_service.get_api_key()

    def _test_connection(self) -> None:
        if self._connection_thread is not None:
            return
        api_key = self._candidate_api_key()
        if not api_key:
            self._show_connection_result(
                ConnectionTestResult(
                    False,
                    "no_key",
                    "No API key configured\nEnter a key or set OPENAI_API_KEY in Settings.",
                )
            )
            return
        try:
            service = OpenAIService(api_key, self.model.currentText(), self.reasoning.currentText())
        except Exception as exc:
            self._show_connection_result(connection_result_for_exception(exc, self.model.currentText()))
            return

        self._set_connection_testing(True)
        self.connection_status.setText("Testing connection…")
        self.connection_status.setToolTip("")
        self._connection_thread = QThread(self)
        self._connection_worker = ConnectionTestWorker(service)
        self._connection_worker.moveToThread(self._connection_thread)
        self._connection_thread.started.connect(self._connection_worker.run)
        self._connection_worker.finished.connect(self._connection_finished)
        self._connection_worker.done.connect(self._connection_thread.quit)
        self._connection_thread.finished.connect(self._connection_thread_finished)
        self._connection_thread.start()

    @Slot(object)
    def _connection_finished(self, result: ConnectionTestResult) -> None:
        self._show_connection_result(result)
        self._set_connection_testing(False)

    def _show_connection_result(self, result: ConnectionTestResult) -> None:
        self.connection_status.setText(result.message)
        self.connection_status.setObjectName("connectionSuccess" if result.success else "connectionWarning")
        self.connection_status.setToolTip(result.technical_detail)
        self.connection_status.style().unpolish(self.connection_status)
        self.connection_status.style().polish(self.connection_status)
        self.connection_test_finished.emit(result)

    def _set_connection_testing(self, testing: bool) -> None:
        self.api_key.setEnabled(not testing)
        self.model.setEnabled(not testing)
        self.reasoning.setEnabled(not testing)
        self.mock_mode.setEnabled(not testing)
        self.clear_key_button.setEnabled(not testing)
        self.test_connection_button.setEnabled(not testing)
        self.dialog_buttons.setEnabled(not testing)

    def _connection_thread_finished(self) -> None:
        if self._connection_thread:
            self._connection_thread.deleteLater()
        if self._connection_worker:
            self._connection_worker.deleteLater()
        self._connection_thread = None
        self._connection_worker = None

    def _populate_profiles(self) -> None:
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
            self.settings_service.clear_saved_api_key()
        elif self.api_key.text().strip():
            self.settings_service.save_api_key(self.api_key.text())
        self.accept()

    def closeEvent(self, event) -> None:
        if self._connection_thread and self._connection_thread.isRunning():
            self.connection_status.setText("Wait for the connection test to finish before closing Settings.")
            event.ignore()
            return
        super().closeEvent(event)
