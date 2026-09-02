"""Main workshop calculator window."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QDoubleSpinBox,
)

from ..config.constants import (
    APP_NAME,
    APP_VERSION,
    MATERIALS,
    TOOL_TYPES,
    TOOL_FAMILY_BY_TYPE,
    tool_family,
)
from ..config.settings import AppSettings
from ..database.database import Database
from ..models.domain import CalculationOutcome, MachiningRequest, MachiningResult, MachineProfile
from ..models.schema import result_from_json
from ..services.calculation_service import CalculationInputError, CalculationService, validate_and_correct_result
from ..services.openai_service import MockOpenAIService, OpenAIService, UnavailableOpenAIService
from ..services.settings_service import SettingsService
from .dialogs import SettingsDialog
from .widgets import DrillPage, EndMillPage, FieldPage, IndexablePage, ReamerPage, TapPage, combo, double_spin


class CalculationWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    done = Signal()

    def __init__(self, calculation_service: CalculationService, request: MachiningRequest, machine: MachineProfile):
        super().__init__()
        self.calculation_service = calculation_service
        self.request = request
        self.machine = machine
        self.cancelled = False

    @Slot()
    def run(self) -> None:
        try:
            outcome = self.calculation_service.calculate(self.request, self.machine)
        except Exception as exc:  # surfaced as a clean status message
            if not self.cancelled:
                self.failed.emit(str(exc))
        else:
            if not self.cancelled:
                self.finished.emit(outcome)
        finally:
            self.done.emit()

    def cancel(self) -> None:
        self.cancelled = True


class MainWindow(QMainWindow):
    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.settings_service = SettingsService(database)
        self.settings = self.settings_service.load()
        self._thread: QThread | None = None
        self._worker: CalculationWorker | None = None
        self._current_outcome: CalculationOutcome | None = None
        self._original_result: MachiningResult | None = None
        self._debug_visible = False

        self.setWindowTitle(f"{APP_NAME} — CNC speeds and feeds")
        self.setMinimumSize(1180, 760)
        self.resize(1450, 900)
        self._build_ui()
        self._load_recent()
        self._update_material_fields()
        self._update_tool_page()
        self._update_status()

    # UI construction -----------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        subtitle = QLabel("A practical CNC calculator with AI-assisted starting data")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        self.status_badge = QLabel()
        self.status_badge.setObjectName("statusBadge")
        header.addWidget(self.status_badge)
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self._open_settings)
        header.addWidget(settings_button)
        root.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_input_panel())
        splitter.addWidget(self._build_result_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([470, 900])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)

    def _build_input_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("inputPanel")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        workflow = QGroupBox("Calculation setup")
        form = QFormLayout(workflow)
        form.setContentsMargins(14, 14, 14, 14)
        form.setVerticalSpacing(10)

        self.machine_combo = QComboBox()
        self._refresh_machine_profiles()
        form.addRow("Machine", self.machine_combo)

        self.material_combo = QComboBox()
        self.material_combo.addItems(list(MATERIALS))
        self.material_combo.setCurrentText(self.settings.last_material)
        self.material_combo.currentTextChanged.connect(self._update_material_fields)
        form.addRow("Material", self.material_combo)

        self.custom_material = QLineEdit()
        self.custom_material.setPlaceholderText("Describe the material")
        form.addRow("Custom material", self.custom_material)

        self.hardness = double_spin(0.0, maximum=70.0, decimals=1, step=0.5)
        form.addRow("Hardness HRC", self.hardness)

        self.tool_combo = QComboBox()
        self.tool_combo.addItems(list(TOOL_TYPES))
        self.tool_combo.setCurrentText(self.settings.last_tool_type)
        self.tool_combo.currentTextChanged.connect(self._update_tool_page)
        form.addRow("Tool", self.tool_combo)

        saved_row = QWidget()
        saved_layout = QHBoxLayout(saved_row)
        saved_layout.setContentsMargins(0, 0, 0, 0)
        self.saved_tool_combo = QComboBox()
        self.saved_tool_combo.addItem("— no saved tool —", None)
        self.saved_tool_combo.currentIndexChanged.connect(self._load_selected_tool)
        save_tool_button = QPushButton("Save current tool")
        save_tool_button.clicked.connect(self._save_current_tool)
        saved_layout.addWidget(self.saved_tool_combo, 1)
        saved_layout.addWidget(save_tool_button)
        form.addRow("Saved tool", saved_row)
        outer.addWidget(workflow)

        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_stack = QStackedWidget()
        self.pages: dict[str, FieldPage] = {
            "drill": DrillPage(),
            "reamer": ReamerPage(),
            "tap": TapPage(),
            "end_mill": EndMillPage(),
            "indexable": IndexablePage(),
        }
        for page in self.pages.values():
            self.page_stack.addWidget(page)
        self._apply_last_coolant()
        page_scroll.setWidget(self.page_stack)
        outer.addWidget(page_scroll, 1)

        recent_group = QGroupBox("Recent calculations")
        recent_layout = QVBoxLayout(recent_group)
        recent_layout.setContentsMargins(10, 10, 10, 10)
        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(145)
        self.recent_list.itemDoubleClicked.connect(self._load_recent_item)
        recent_layout.addWidget(self.recent_list)
        outer.addWidget(recent_group)

        actions = QHBoxLayout()
        self.calculate_button = QPushButton("CALCULATE")
        self.calculate_button.setObjectName("calculateButton")
        self.calculate_button.setMinimumHeight(48)
        self.calculate_button.clicked.connect(self._calculate)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_calculation)
        actions.addWidget(self.calculate_button, 1)
        actions.addWidget(self.cancel_button)
        outer.addLayout(actions)
        self._refresh_saved_tools()
        return panel

    def _build_result_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("resultPanel")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)

        self.result_status = QLabel("Enter the machining parameters, then calculate.")
        self.result_status.setObjectName("resultStatus")
        outer.addWidget(self.result_status)
        self.result_banner = QLabel()
        self.result_banner.setObjectName("resultBanner")
        self.result_banner.setVisible(False)
        outer.addWidget(self.result_banner)

        key_group = QGroupBox("Recommended starting values")
        key_layout = QGridLayout(key_group)
        key_layout.setContentsMargins(14, 14, 14, 14)
        key_layout.setHorizontalSpacing(12)
        key_layout.setVerticalSpacing(12)
        self.result_fields: dict[str, QDoubleSpinBox] = {}
        self.result_cards: dict[str, QFrame] = {}
        specs = [
            ("rpm", "SPINDLE", "RPM"),
            ("feed_mm_min", "FEED", "mm/min"),
            ("axial_doc_mm", "DOC", "mm"),
            ("stepover_mm", "STEPOVER", "mm"),
            ("peck_mm", "PECK Q", "mm"),
            ("pre_ream_size_mm", "PRE-REAM SIZE", "mm"),
            ("tap_drill_mm", "TAPPING DRILL", "mm"),
        ]
        for index, (key, label, suffix) in enumerate(specs):
            card = QFrame()
            card.setObjectName("valueCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 12)
            small = QLabel(label)
            small.setObjectName("valueLabel")
            value = double_spin(0.0, maximum=1000000.0, decimals=3, step=0.1)
            value.setSuffix(f"  {suffix}")
            value.setMinimumHeight(42)
            value.setFont(QFont("Segoe UI", 16, QFont.Bold))
            value.setToolTip("This value can be adjusted before saving a workshop setting.")
            card_layout.addWidget(small)
            card_layout.addWidget(value)
            self.result_fields[key] = value
            self.result_cards[key] = card
            key_layout.addWidget(card, index // 4, index % 4)
        outer.addWidget(key_group)

        info_group = QGroupBox("Secondary information")
        info_form = QFormLayout(info_group)
        info_form.setContentsMargins(14, 10, 14, 10)
        self.info_labels: dict[str, QLabel] = {}
        for key, label in (
            ("cutting_speed", "Cutting speed"),
            ("feed_per_tooth", "Feed per tooth"),
            ("feed_per_rev", "Feed per rev"),
            ("pre_ream_range", "Pre-ream range"),
            ("cycle", "Cycle / method"),
            ("coolant", "Coolant"),
            ("confidence", "Confidence"),
        ):
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.info_labels[key] = value
            info_form.addRow(label, value)
        outer.addWidget(info_group)

        notes_group = QGroupBox("Machining notes")
        notes_layout = QVBoxLayout(notes_group)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(125)
        self.notes.setPlaceholderText("Notes and warnings will appear here.")
        notes_layout.addWidget(self.notes)
        outer.addWidget(notes_group)

        buttons = QHBoxLayout()
        self.save_preference_button = QPushButton("Save as workshop setting")
        self.save_preference_button.setEnabled(False)
        self.save_preference_button.clicked.connect(self._save_workshop_setting)
        self.retry_button = QPushButton("Retry")
        self.retry_button.setVisible(False)
        self.retry_button.clicked.connect(self._calculate)
        self.debug_button = QPushButton("Show advanced / debug")
        self.debug_button.setCheckable(True)
        self.debug_button.toggled.connect(self._toggle_debug)
        buttons.addWidget(self.save_preference_button)
        buttons.addWidget(self.retry_button)
        buttons.addStretch(1)
        buttons.addWidget(self.debug_button)
        outer.addLayout(buttons)

        self.debug_group = QGroupBox("Advanced / Debug")
        debug_layout = QVBoxLayout(self.debug_group)
        self.debug_tabs = QStackedWidget()
        self.debug_editors: dict[str, QPlainTextEdit] = {}
        for key, title in (
            ("normalized", "Normalized request"),
            ("prompt", "Generated request"),
            ("raw", "Raw structured response"),
            ("validated", "Validated final response"),
            ("meta", "Cache / response metadata"),
        ):
            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            editor.setLineWrapMode(QPlainTextEdit.NoWrap)
            self.debug_editors[key] = editor
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, 0, 0, 0)
            tab_layout.addWidget(editor)
            self.debug_tabs.addWidget(tab)
        # A small tab bar is more compact than five always-visible text boxes.
        from PySide6.QtWidgets import QTabBar

        self.debug_bar = QTabBar()
        for title in ("Normalized", "Request", "Raw", "Validated", "Metadata"):
            self.debug_bar.addTab(title)
        self.debug_bar.currentChanged.connect(self.debug_tabs.setCurrentIndex)
        debug_layout.addWidget(self.debug_bar)
        debug_layout.addWidget(self.debug_tabs)
        self.debug_group.setVisible(False)
        outer.addWidget(self.debug_group, 1)
        return panel

    # Selection and persistence ------------------------------------------
    def _refresh_machine_profiles(self) -> None:
        current = getattr(self, "machine_combo", None)
        current_text = current.currentText() if current else self.settings.last_machine
        profiles = self.database.machine_profiles()
        self.machine_profiles: dict[str, MachineProfile] = {
            profile["name"]: MachineProfile(
                name=profile["name"],
                max_rpm=float(profile["max_rpm"]),
                max_feed_mm_min=float(profile["max_feed_mm_min"]),
                spindle_power_kw=profile.get("spindle_power_kw"),
                coolant_capability=profile.get("coolant_capability", ""),
                rigidity=profile.get("rigidity", "medium"),
            )
            for profile in profiles
        }
        if current is not None:
            current.blockSignals(True)
            current.clear()
            current.addItems(list(self.machine_profiles))
            current.setCurrentText(current_text if current_text in self.machine_profiles else "Generic CNC Mill")
            current.blockSignals(False)

    def _refresh_saved_tools(self) -> None:
        if not hasattr(self, "saved_tool_combo"):
            return
        self.saved_tool_combo.blockSignals(True)
        self.saved_tool_combo.clear()
        self.saved_tool_combo.addItem("— no saved tool —", None)
        for tool in self.database.saved_tools():
            self.saved_tool_combo.addItem(tool["name"], tool["id"])
        self.saved_tool_combo.blockSignals(False)

    def _apply_last_coolant(self) -> None:
        coolant = self.settings.last_coolant
        for family in ("tap", "end_mill", "indexable"):
            self.pages[family].load_values({"coolant_type": coolant})
        flood = coolant.casefold() == "flood coolant" or not coolant
        for family in ("drill", "reamer"):
            self.pages[family].load_values({"flood_coolant": flood, "internal_coolant": coolant.casefold() == "through-tool coolant"})

    def _update_material_fields(self, _value: str = "") -> None:
        if not hasattr(self, "material_combo"):
            return
        material = self.material_combo.currentText()
        custom = material == "Custom / Other"
        hardened = "hardened" in material.casefold() or material in {"Toolox 44"}
        self.custom_material.setVisible(custom)
        self.custom_material.parentWidget().layout().labelForField(self.custom_material).setVisible(custom)  # type: ignore[union-attr]
        hardness_label = self.hardness.parentWidget().layout().labelForField(self.hardness)  # type: ignore[union-attr]
        self.hardness.setVisible(hardened or custom)
        hardness_label.setVisible(hardened or custom)

    def _update_tool_page(self, _value: str = "") -> None:
        if not hasattr(self, "tool_combo"):
            return
        tool_type = self.tool_combo.currentText()
        family = tool_family(tool_type)
        self.page_stack.setCurrentWidget(self.pages[family])
        if family == "end_mill":
            ball_nose = "ball nose" in tool_type.casefold()
            self.pages[family].set_field_visible("ball_nose_mode", ball_nose)
            self.pages[family].set_field_visible("surface_finish_priority", ball_nose)
        self.saved_tool_combo.setCurrentIndex(0)

    def _machine(self) -> MachineProfile:
        return self.machine_profiles.get(
            self.machine_combo.currentText(),
            MachineProfile("Generic CNC Mill", 12000.0, 10000.0, rigidity="medium"),
        )

    def _collect_request(self) -> MachiningRequest:
        tool_type = self.tool_combo.currentText()
        page = self.pages[tool_family(tool_type)]
        parameters = page.values()
        operation = str(parameters.pop("operation", tool_type))
        hardness = self.hardness.value() if self.hardness.isVisible() and self.hardness.value() > 0 else None
        custom_material = self.custom_material.text().strip() if self.custom_material.isVisible() else ""
        return MachiningRequest(
            machine=self.machine_combo.currentText(),
            material=self.material_combo.currentText(),
            custom_material=custom_material,
            hardness_hrc=hardness,
            tool_type=tool_type,
            operation=operation,
            parameters=parameters,
        )

    def _save_preferences(self, request: MachiningRequest) -> None:
        self.settings.last_machine = request.machine
        self.settings.last_material = request.material
        self.settings.last_tool_type = request.tool_type
        coolant = request.parameters.get("coolant_type")
        if coolant:
            self.settings.last_coolant = str(coolant)
        self.settings_service.save(self.settings)

    def _load_selected_tool(self, index: int) -> None:
        if index <= 0:
            return
        tool_id = self.saved_tool_combo.itemData(index)
        saved = self.database.get_saved_tool(int(tool_id)) if tool_id is not None else None
        if not saved:
            return
        self.tool_combo.setCurrentText(saved["tool_type"])
        try:
            values = json.loads(saved["tool_json"])
        except json.JSONDecodeError:
            return
        self.pages[tool_family(self.tool_combo.currentText())].load_values(values)

    def _save_current_tool(self) -> None:
        page = self.pages[tool_family(self.tool_combo.currentText())]
        values = page.values()
        from PySide6.QtWidgets import QInputDialog

        name, accepted = QInputDialog.getText(self, "Save tool", "Tool name")
        if not accepted or not name.strip():
            return
        self.database.save_tool(name, self.tool_combo.currentText(), values)
        self._refresh_saved_tools()
        self.result_status.setText(f"Saved tool: {name.strip()}")

    def _load_recent(self) -> None:
        if not hasattr(self, "recent_list"):
            return
        self.recent_list.clear()
        for row in self.database.recent(12):
            try:
                normalized = json.loads(row["normalized_request_json"])
            except json.JSONDecodeError:
                continue
            label = f"{normalized.get('tool_type', '').title()} · {normalized.get('material', '').title()} · {row['created_at'][:16].replace('T', ' ')}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, row)
            self.recent_list.addItem(item)

    def _load_recent_item(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.UserRole)
        if not row:
            return
        try:
            normalized = json.loads(row["normalized_request_json"])
            result = result_from_json(row["result_json"])
        except (json.JSONDecodeError, ValueError) as exc:
            QMessageBox.warning(self, "Recent calculation", f"This saved calculation could not be reopened: {exc}")
            return
        self._set_combo_casefold(self.machine_combo, normalized.get("machine", ""))
        self._set_combo_casefold(self.material_combo, normalized.get("material", ""))
        self._set_combo_casefold(self.tool_combo, normalized.get("tool_type", ""))
        self.custom_material.setText(normalized.get("custom_material", ""))
        self.hardness.setValue(float(normalized.get("hardness_hrc") or 0))
        page = self.pages[tool_family(self.tool_combo.currentText())]
        page_values = dict(normalized.get("parameters", {}))
        if "operation" in page.fields:
            page_values["operation"] = normalized.get("operation", page_values.get("operation", ""))
        page.load_values(page_values)
        outcome = CalculationOutcome(
            result=result,
            normalized_request=normalized,
            request_hash=row["request_hash"],
            source="cache",
            cache_hit=True,
            model="saved recent calculation",
            validated_response=json.dumps(result.to_dict(), indent=2),
        )
        self._show_result(outcome)
        self.result_status.setText("Reopened recent calculation")

    # Calculation lifecycle ----------------------------------------------
    def _make_ai_service(self):
        if self.settings.mock_mode:
            return MockOpenAIService(self.settings.model, self.settings.reasoning_effort)
        api_key = self.settings_service.get_api_key()
        if not api_key:
            # The calculation service checks SQLite before calling this object,
            # so a cached/workshop result remains available offline.
            return UnavailableOpenAIService(self.settings.model)
        return OpenAIService(api_key, self.settings.model, self.settings.reasoning_effort)

    def _calculate(self) -> None:
        if self._thread is not None:
            return
        try:
            request = self._collect_request()
            ai_service = self._make_ai_service()
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._save_preferences(request)
        self._set_calculating(True)
        self.result_status.setText("Calculating machining parameters…")
        self.result_banner.setVisible(False)
        self.retry_button.setVisible(False)
        self.notes.clear()
        worker_service = CalculationService(self.database, ai_service)
        self._thread = QThread(self)
        self._worker = CalculationWorker(worker_service, request, self._machine())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._calculation_finished)
        self._worker.failed.connect(self._calculation_failed)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._calculation_thread_finished)
        self._thread.start()

    def _set_calculating(self, calculating: bool) -> None:
        self.calculate_button.setEnabled(not calculating)
        self.cancel_button.setEnabled(calculating)
        self.machine_combo.setEnabled(not calculating)
        self.material_combo.setEnabled(not calculating)
        self.tool_combo.setEnabled(not calculating)

    def _cancel_calculation(self) -> None:
        if self._worker:
            self._worker.cancel()
        self.result_status.setText("Calculation cancelled")
        self._set_calculating(False)

    @Slot(object)
    def _calculation_finished(self, outcome: CalculationOutcome) -> None:
        self._show_result(outcome)
        self.result_status.setText("Calculation ready")
        self._load_recent()
        self._set_calculating(False)

    @Slot(str)
    def _calculation_failed(self, message: str) -> None:
        self._show_error(message)
        self.result_status.setText("Calculation could not be completed")
        self._set_calculating(False)

    def _calculation_thread_finished(self) -> None:
        if self._thread:
            self._thread.deleteLater()
        if self._worker:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

    def _show_error(self, message: str) -> None:
        self.result_banner.setText(f"Could not calculate: {message}")
        self.result_banner.setObjectName("errorBanner")
        self.result_banner.setVisible(True)
        self.retry_button.setVisible(True)
        self.result_status.setText("Check the inputs or retry")
        self.result_banner.style().unpolish(self.result_banner)
        self.result_banner.style().polish(self.result_banner)

    # Result display ------------------------------------------------------
    def _show_result(self, outcome: CalculationOutcome) -> None:
        self._current_outcome = outcome
        self._original_result = outcome.result.copy()
        result = outcome.result
        family = tool_family(self.tool_combo.currentText())
        visible = {
            "rpm": True,
            "feed_mm_min": True,
            "axial_doc_mm": family in {"end_mill", "indexable"},
            "stepover_mm": family in {"end_mill", "indexable"},
            "peck_mm": family == "drill" and result.peck_mm is not None,
            "pre_ream_size_mm": family == "reamer",
            "tap_drill_mm": family == "tap",
        }
        for key, card in self.result_cards.items():
            card.setVisible(visible.get(key, False) and getattr(result, key) is not None)
            value = getattr(result, key)
            if value is not None:
                self.result_fields[key].setValue(float(value))

        self.info_labels["cutting_speed"].setText(self._format_value(result.cutting_speed_m_min, "m/min"))
        self.info_labels["feed_per_tooth"].setText(self._format_value(result.feed_per_tooth_mm, "mm/tooth"))
        self.info_labels["feed_per_rev"].setText(self._format_value(result.feed_per_rev_mm, "mm/rev"))
        self.info_labels["pre_ream_range"].setText(result.pre_ream_range_mm or "—")
        cycle = result.recommended_cycle or "—"
        self.info_labels["cycle"].setText(cycle)
        self.info_labels["coolant"].setText(result.coolant or "—")
        self.info_labels["confidence"].setText(result.confidence.title())

        all_notes = list(result.notes)
        all_notes.extend(result.warnings)
        all_notes.extend(f"Local validation: {item}" for item in outcome.validation_corrections)
        self.notes.setPlainText("\n".join(dict.fromkeys(all_notes)) or "No additional notes.")

        if outcome.source == "mock":
            banner = "DEVELOPMENT MOCK RESULT — not cached or suitable as production data"
        elif outcome.source == "workshop":
            banner = "SAVED WORKSHOP SETTING — local preference takes priority"
        elif outcome.source == "cache":
            banner = "Cached result — no API request was made"
        else:
            banner = f"AI result from {outcome.model}"
        self.result_banner.setObjectName("resultBanner")
        self.result_banner.setText(banner)
        self.result_banner.setVisible(True)
        self.save_preference_button.setEnabled(outcome.source != "mock")
        self.retry_button.setVisible(False)
        self._populate_debug(outcome)

    @staticmethod
    def _format_value(value: float | None, suffix: str) -> str:
        if value is None:
            return "—"
        if abs(value - round(value)) < 1e-8:
            text = f"{value:,.0f}"
        else:
            text = f"{value:,.3f}".rstrip("0").rstrip(".")
        return f"{text} {suffix}"

    def _result_from_controls(self) -> MachiningResult:
        if self._original_result is None:
            raise CalculationInputError("There is no result to save yet.")
        result = self._original_result.copy()
        for key, widget in self.result_fields.items():
            if self.result_cards[key].isVisible():
                setattr(result, key, widget.value())
        return result

    def _save_workshop_setting(self) -> None:
        if not self._current_outcome:
            return
        try:
            request = self._collect_request()
            preferred = self._result_from_controls()
            preferred, corrections = validate_and_correct_result(preferred, request, self._machine())
            CalculationService(self.database, MockOpenAIService()).save_workshop_preference(self._current_outcome, preferred)
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._original_result = preferred.copy()
        self._show_result(
            replace(
                self._current_outcome,
                result=preferred,
                validation_corrections=list(self._current_outcome.validation_corrections) + corrections,
                source="workshop",
            )
        )
        self.result_banner.setText("SAVED WORKSHOP SETTING — this local recommendation will be used next time")
        self.result_banner.setVisible(True)
        self.result_status.setText("Workshop setting saved")

    def _populate_debug(self, outcome: CalculationOutcome) -> None:
        self.debug_editors["normalized"].setPlainText(json.dumps(outcome.normalized_request, indent=2, ensure_ascii=False, sort_keys=True))
        self.debug_editors["prompt"].setPlainText(outcome.prompt or "(not regenerated for a cache/workshop hit)")
        self.debug_editors["raw"].setPlainText(outcome.raw_response or "(none)")
        self.debug_editors["validated"].setPlainText(outcome.validated_response or json.dumps(outcome.result.to_dict(), indent=2))
        metadata = {
            "cache_hit": outcome.cache_hit,
            "source": outcome.source,
            "request_hash": outcome.request_hash,
            "model": outcome.model,
            "response_id": outcome.response_id,
            "usage": outcome.usage,
            "validation_corrections": outcome.validation_corrections,
        }
        self.debug_editors["meta"].setPlainText(json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True))

    def _toggle_debug(self, visible: bool) -> None:
        self._debug_visible = visible
        self.debug_group.setVisible(visible)
        self.debug_button.setText("Hide advanced / debug" if visible else "Show advanced / debug")

    # Settings and helpers -------------------------------------------------
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.database, self.settings, self)
        if dialog.exec() == dialog.Accepted:
            self.settings = self.settings_service.load()
            self._refresh_machine_profiles()
            self._update_status()

    def _update_status(self) -> None:
        if self.settings.mock_mode:
            text = "DEVELOPMENT MOCK MODE"
            self.status_badge.setObjectName("mockBadge")
        elif self.settings_service.get_api_key():
            text = f"AI READY · {self.settings.model}"
            self.status_badge.setObjectName("readyBadge")
        else:
            text = "API KEY NEEDED"
            self.status_badge.setObjectName("warningBadge")
        self.status_badge.setText(text)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    @staticmethod
    def _set_combo_casefold(widget: QComboBox, value: str) -> None:
        for index in range(widget.count()):
            if widget.itemText(index).casefold() == str(value).casefold():
                widget.setCurrentIndex(index)
                return

    def closeEvent(self, event) -> None:
        if self._worker:
            self._worker.cancel()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)
        event.accept()


def apply_styles(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        QWidget { font-family: 'Segoe UI'; font-size: 10pt; }
        QMainWindow, QDialog { background: #f3f5f7; }
        QGroupBox { background: #ffffff; border: 1px solid #d5dbe1; border-radius: 8px; margin-top: 9px; padding-top: 9px; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #4c5965; font-weight: 600; }
        QFrame#inputPanel, QFrame#resultPanel { background: transparent; }
        QLabel#appTitle { font-size: 22pt; font-weight: 700; color: #17212b; }
        QLabel#subtitle, QLabel#hint { color: #66727d; }
        QLabel#formHeading { color: #2f6d84; font-size: 9pt; font-weight: 700; letter-spacing: 1px; padding-top: 5px; }
        QLabel#statusBadge, QLabel#readyBadge, QLabel#mockBadge, QLabel#warningBadge { padding: 7px 12px; border-radius: 14px; font-weight: 700; }
        QLabel#readyBadge { background: #d9f1e4; color: #17643a; }
        QLabel#mockBadge { background: #fff0bd; color: #765b00; }
        QLabel#warningBadge { background: #fde0d8; color: #8a2d1d; }
        QLabel#resultStatus { color: #4c5965; font-size: 11pt; }
        QLabel#resultBanner { background: #e1f0f5; color: #205a6e; padding: 8px 12px; border-radius: 5px; font-weight: 600; }
        QLabel#errorBanner { background: #fde0d8; color: #8a2d1d; padding: 8px 12px; border-radius: 5px; font-weight: 600; }
        QFrame#valueCard { background: #f8fafb; border: 1px solid #d8e0e5; border-radius: 7px; }
        QLabel#valueLabel { color: #51606b; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }
        QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit { min-height: 30px; }
        QPushButton { min-height: 30px; padding: 3px 12px; }
        QPushButton#calculateButton { background: #1d6f86; color: white; font-weight: 700; font-size: 12pt; border-radius: 6px; }
        QPushButton#calculateButton:hover { background: #15566a; }
        QPlainTextEdit { background: #fbfcfd; border: 1px solid #d5dbe1; }
        QListWidget { border: 1px solid #d5dbe1; border-radius: 5px; }
        QSplitter::handle { background: #d5dbe1; }
        """
    )
