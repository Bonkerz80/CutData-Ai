"""Main workshop calculator window."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, QRect, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QPixmap
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
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from ..config.constants import (
    APP_NAME,
    APP_VERSION,
    COMPANY_NAME,
    MATERIALS,
    PRODUCT_TAGLINE,
    PUBLISHER_NAME,
    PPT_HORIZONTAL_LOGO_PATH,
    SUPPORTED_MODELS,
    TOOL_TYPES,
    WINDOWS_ICON_PATH,
    compatible_tool_type,
    model_display_name,
    tool_family,
)
from ..config.operations import (
    legacy_operation_warning,
    default_operation_for_tool,
    is_legacy_operation,
    operations_for_tool,
)
from ..config.settings import AppSettings
from ..database.database import Database
from ..models.domain import CalculationOutcome, MachiningRequest, MachiningResult, MachineProfile
from ..models.schema import result_from_json
from ..services.calculation_service import CalculationService
from ..services.derived_values import (
    axial_doc_ratio,
    hole_ld_ratio,
    material_removal_rate_cm3_min,
    radial_engagement_percent,
    torque_from_power,
    usage_percent,
)
from ..services.openai_service import (
    ConnectionTestResult,
    MockOpenAIService,
    OpenAIService,
    UnavailableOpenAIService,
)
from ..services.settings_service import SettingsService
from ..services.recent_summary import recent_item_text
from .dialogs import AboutDialog, SettingsDialog
from .result_layout import peck_display, result_layout_for_family, effective_lateral_value
from .theme import apply_theme
from .widgets import DrillPage, EndMillPage, FieldPage, IndexablePage, ReamerPage, TapPage, combo, double_spin


class CalculationWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)
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
                self.failed.emit(
                    {
                        "message": str(exc),
                        "context": dict(getattr(self.calculation_service, "last_failure_context", {}) or {}),
                    }
                )
        else:
            if not self.cancelled:
                self.finished.emit(outcome)
        finally:
            self.done.emit()

    def cancel(self) -> None:
        self.cancelled = True


def normalise_window_state(value: Any) -> dict[str, Any]:
    """Keep persisted geometry usable across monitors and older versions."""

    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("x", "y", "width", "height"):
        try:
            result[key] = int(value[key])
        except (KeyError, TypeError, ValueError):
            return {}
    if result["width"] <= 0 or result["height"] <= 0:
        return {}
    maximized = value.get("maximized", False)
    if isinstance(maximized, str):
        maximized = maximized.strip().casefold() in {"1", "true", "yes", "on"}
    result["maximized"] = bool(maximized)
    return result


class MainWindow(QMainWindow):
    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.settings_service = SettingsService(database)
        self.settings = self.settings_service.load()
        self._restoring_state = True
        self._thread: QThread | None = None
        self._worker: CalculationWorker | None = None
        self._current_outcome: CalculationOutcome | None = None
        self._debug_visible = False
        self._api_error = False
        self.ai_service = None
        self._operation_by_tool: dict[str, str] = {}
        self._active_tool_type = ""
        apply_theme(QApplication.instance(), self.settings.appearance)

        self.setWindowTitle(f"{PUBLISHER_NAME} {APP_NAME} {APP_VERSION} — CNC Machining Calculator")
        self.setWindowIcon(QIcon(str(WINDOWS_ICON_PATH)))
        self.setMinimumSize(1180, 760)
        self.resize(1450, 900)
        self._build_ui()
        self._restore_calculator_state()
        self._restore_window_state()
        self._load_recent()
        self._update_material_fields()
        self._update_tool_page()
        self._reload_ai_service()
        self._update_status()
        self._restoring_state = False

    # UI construction -----------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 16)
        root.setSpacing(10)

        header_frame = QFrame()
        header_frame.setObjectName("brandHeader")
        header_frame.setFixedHeight(88)
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(12, 8, 12, 8)
        header.setSpacing(14)

        ppt_block = QFrame()
        ppt_block.setObjectName("pptBrandBlock")
        ppt_block.setMinimumWidth(340)
        ppt_block.setMaximumWidth(360)
        ppt_layout = QHBoxLayout(ppt_block)
        ppt_layout.setContentsMargins(8, 6, 12, 6)
        ppt_layout.setSpacing(10)
        logo_surface = QFrame()
        logo_surface.setObjectName("pptLogoSurface")
        logo_surface.setFixedSize(148, 60)
        logo_layout = QVBoxLayout(logo_surface)
        logo_layout.setContentsMargins(7, 6, 7, 6)
        logo = QLabel()
        logo.setPixmap(
            QPixmap(str(PPT_HORIZONTAL_LOGO_PATH)).scaled(
                134, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
        logo.setAlignment(Qt.AlignCenter)
        logo.setAccessibleName(f"Official {PUBLISHER_NAME} logo")
        logo_layout.addWidget(logo)
        ppt_layout.addWidget(logo_surface)
        company = QLabel(COMPANY_NAME.replace(" & ", "\n& "))
        company.setObjectName("pptCompanyName")
        company.setWordWrap(True)
        company.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        ppt_layout.addWidget(company, 1)
        self.ppt_brand_block = ppt_block
        header.addWidget(ppt_block)

        product_box = QVBoxLayout()
        product_box.setContentsMargins(2, 0, 0, 0)
        product_box.setSpacing(1)
        title = QLabel(APP_NAME)
        title.setObjectName("headerProduct")
        subtitle = QLabel(PRODUCT_TAGLINE)
        subtitle.setObjectName("headerTagline")
        product_box.addStretch(1)
        product_box.addWidget(title)
        product_box.addWidget(subtitle)
        product_box.addStretch(1)
        self.header_product = title
        self.header_tagline = subtitle
        header.addLayout(product_box, 1)
        header.addStretch(1)
        self.status_badge = QLabel()
        self.status_badge.setObjectName("statusBadge")
        header.addWidget(self.status_badge)
        about_button = QPushButton("About")
        about_button.setObjectName("headerButton")
        about_button.clicked.connect(self._open_about)
        self.about_button = about_button
        header.addWidget(about_button)
        settings_button = QPushButton("Settings")
        settings_button.setObjectName("headerButton")
        settings_button.clicked.connect(self._open_settings)
        self.settings_button = settings_button
        header.addWidget(settings_button)
        self.header_frame = header_frame
        root.addWidget(header_frame)
        brand_rule = QFrame()
        brand_rule.setObjectName("brandRule")
        brand_rule.setFixedHeight(3)
        root.addWidget(brand_rule)
        self.api_status_notice = QLabel()
        self.api_status_notice.setObjectName("apiStatusNotice")
        self.api_status_notice.setWordWrap(True)
        self.api_status_notice.setVisible(False)
        root.addWidget(self.api_status_notice)

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
        workflow.setObjectName("setupGroup")
        form = QFormLayout(workflow)
        form.setContentsMargins(14, 14, 14, 14)
        form.setVerticalSpacing(10)

        self.machine_combo = QComboBox()
        self._compact_combo(self.machine_combo)
        self._refresh_machine_profiles()
        form.addRow("Machine", self.machine_combo)

        self.material_combo = QComboBox()
        self._compact_combo(self.material_combo)
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
        self._compact_combo(self.tool_combo)
        self.tool_combo.addItems(list(TOOL_TYPES))
        self.tool_combo.setCurrentText(self.settings.last_tool_type)
        self.tool_combo.currentTextChanged.connect(self._tool_changed)
        form.addRow("Tool", self.tool_combo)

        outer.addWidget(workflow)

        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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
            page.operation_changed.connect(self._operation_changed)
        self._apply_last_coolant()
        page_scroll.setWidget(self.page_stack)
        outer.addWidget(page_scroll, 1)

        recent_group = QGroupBox("Recent calculations")
        recent_group.setObjectName("recentGroup")
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
        return panel

    @staticmethod
    def _compact_combo(widget: QComboBox) -> None:
        """Allow form combos to shrink and let their popup show long values."""

        widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        widget.setMinimumContentsLength(0)
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _build_result_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("resultPanel")
        self.result_panel = panel
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        result_scroll = QScrollArea()
        result_scroll.setObjectName("resultScroll")
        result_scroll.setWidgetResizable(True)
        result_scroll.setFrameShape(QFrame.NoFrame)
        result_content = QWidget()
        result_content.setObjectName("resultContent")
        outer = QVBoxLayout(result_content)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)
        result_scroll.setWidget(result_content)
        panel_layout.addWidget(result_scroll)
        self.result_scroll = result_scroll

        self.result_status = QLabel("Ready to calculate")
        self.result_status.setObjectName("resultStatus")
        outer.addWidget(self.result_status)
        self.result_banner = QLabel()
        self.result_banner.setObjectName("resultBanner")
        self.result_banner.setWordWrap(True)
        self.result_banner.setVisible(False)

        key_group = QGroupBox("Primary AI recommendation")
        key_group.setObjectName("primaryGroup")
        key_layout = QGridLayout(key_group)
        key_layout.setContentsMargins(14, 14, 14, 14)
        key_layout.setHorizontalSpacing(12)
        key_layout.setVerticalSpacing(12)
        key_layout.setAlignment(Qt.AlignTop)
        self.primary_group = key_group
        self.result_key_layout = key_layout
        self.result_fields: dict[str, QLabel] = {}
        self.result_cards: dict[str, QFrame] = {}
        self.result_titles: dict[str, QLabel] = {}
        specs = [
            ("rpm", "SPINDLE", "RPM"),
            ("feed_mm_min", "FEED", "mm/min"),
            ("axial_doc_mm", "DOC", "mm"),
            ("stepover_mm", "WOC / STEPOVER", "mm"),
            ("peck_mm", "PECK / Q", "mm"),
            ("pre_ream_size_mm", "PRE-REAM SIZE", "mm"),
            ("tap_drill_mm", "TAPPING DRILL", "mm"),
        ]
        for index, (key, label, suffix) in enumerate(specs):
            card = QFrame()
            card.setObjectName("valueCard")
            card.setMinimumWidth(145)
            card.setMaximumWidth(245)
            card.setMinimumHeight(82)
            card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 12)
            small = QLabel(label)
            small.setWordWrap(True)
            self.result_titles[key] = small
            small.setObjectName("valueLabel")
            value = QLabel("—")
            value.setObjectName("resultValue")
            value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setMinimumHeight(42)
            value.setFont(QFont("Segoe UI", 16, QFont.Bold))
            value.setProperty("unit", suffix)
            # Text must fill the existing card, not resize it as results arrive.
            value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            card_layout.addWidget(small)
            card_layout.addWidget(value)
            self.result_fields[key] = value
            self.result_cards[key] = card
            key_layout.addWidget(card, index // 4, index % 4)
        outer.addWidget(key_group)

        info_group = QGroupBox("Secondary information")
        info_group.setObjectName("secondaryGroup")
        info_layout = QGridLayout(info_group)
        info_layout.setContentsMargins(14, 10, 14, 10)
        info_layout.setHorizontalSpacing(18)
        info_layout.setVerticalSpacing(5)
        info_layout.setColumnMinimumWidth(0, 135)
        info_layout.setColumnStretch(1, 1)
        self.info_labels: dict[str, QLabel] = {}
        self.info_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label in (
            ("cutting_speed", "Cutting speed"),
            ("feed_per_tooth", "Feed per tooth"),
            ("feed_per_rev", "Feed per rev"),
            ("pre_ream_range", "Pre-ream range"),
            ("cycle", "Cycle / method"),
            ("coolant", "Coolant"),
            ("confidence", "Confidence"),
        ):
            label_widget = QLabel(label)
            label_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            value = QLabel("—")
            value.setObjectName("infoValue")
            value.setWordWrap(True)
            value.setMinimumHeight(24)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.info_labels[key] = value
            self.info_rows[key] = (label_widget, value)
            row = len(self.info_rows) - 1
            info_layout.addWidget(label_widget, row, 0)
            info_layout.addWidget(value, row, 1)
        self.info_group = info_group
        outer.addWidget(info_group)

        self.derived_group = QGroupBox("Derived data")
        self.derived_group.setObjectName("secondaryGroup")
        derived_layout = QGridLayout(self.derived_group)
        derived_layout.setContentsMargins(14, 10, 14, 10)
        derived_layout.setHorizontalSpacing(18)
        derived_layout.setVerticalSpacing(5)
        derived_layout.setColumnMinimumWidth(0, 135)
        derived_layout.setColumnStretch(1, 1)
        self.derived_labels: dict[str, QLabel] = {}
        self.derived_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label in (
            ("hole_ld_ratio", "Hole L/D ratio"),
            ("radial_engagement", "Radial engagement"),
            ("axial_doc_ratio", "Axial DOC"),
            ("mrr", "Calculated MRR"),
            ("rpm_usage", "Machine RPM usage"),
            ("feed_usage", "Machine feed usage"),
            ("tap_relationship", "Tapping relationship"),
        ):
            label_widget = QLabel(label)
            value = QLabel("—")
            value.setWordWrap(True)
            value.setMinimumHeight(24)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.derived_labels[key] = value
            self.derived_rows[key] = (label_widget, value)
            label_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            row = len(self.derived_rows) - 1
            derived_layout.addWidget(label_widget, row, 0)
            derived_layout.addWidget(value, row, 1)
        outer.addWidget(self.derived_group)

        self.ai_context_group = QGroupBox("AI context / estimates")
        self.ai_context_group.setObjectName("secondaryGroup")
        ai_context_layout = QGridLayout(self.ai_context_group)
        ai_context_layout.setContentsMargins(14, 10, 14, 10)
        ai_context_layout.setHorizontalSpacing(18)
        ai_context_layout.setVerticalSpacing(5)
        ai_context_layout.setColumnMinimumWidth(0, 135)
        ai_context_layout.setColumnStretch(1, 1)
        self.ai_context_labels: dict[str, QLabel] = {}
        self.ai_context_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label in (
            ("engagement_description", "AI engagement context"),
            ("setup_risk", "AI setup risk"),
            ("recommendation_summary", "AI summary"),
            ("power", "AI estimated spindle power"),
            ("torque", "AI estimated spindle torque"),
        ):
            label_widget = QLabel(label)
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.ai_context_labels[key] = value
            self.ai_context_rows[key] = (label_widget, value)
            label_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            row = len(self.ai_context_rows) - 1
            ai_context_layout.addWidget(label_widget, row, 0)
            ai_context_layout.addWidget(value, row, 1)
        self.ai_context_group.setVisible(False)

        notes_group = QGroupBox("Machining notes")
        notes_group.setObjectName("secondaryGroup")
        notes_layout = QVBoxLayout(notes_group)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setFixedHeight(72)
        self.notes.setPlaceholderText("AI machining notes and warnings will appear here.")
        notes_layout.addWidget(self.notes)
        self.notes_group = notes_group
        outer.addWidget(notes_group)
        # Optional content follows the stable calculator display.
        outer.addWidget(self.ai_context_group)
        outer.addWidget(self.result_banner)

        buttons = QHBoxLayout()
        self.retry_button = QPushButton("Retry")
        self.retry_button.setVisible(False)
        self.retry_button.clicked.connect(self._calculate)
        self.debug_button = QPushButton("Show advanced / debug")
        self.debug_button.setCheckable(True)
        self.debug_button.toggled.connect(self._toggle_debug)
        buttons.addWidget(self.retry_button)
        buttons.addStretch(1)
        buttons.addWidget(self.debug_button)
        outer.addLayout(buttons)

        self.debug_group = QGroupBox("Advanced / Debug")
        self.debug_group.setObjectName("secondaryGroup")
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
        outer.addStretch(1)
        return panel

    # Selection and persistence ------------------------------------------
    def _calculator_state_payload(self) -> dict[str, Any]:
        active_tool = self._active_tool_type or self.tool_combo.currentText()
        family = tool_family(active_tool)
        active_values = self.pages[family].values()
        active_operation = active_values.get("operation", "")
        if active_tool and active_operation:
            self._operation_by_tool[active_tool] = str(active_operation)
        current_tool = self.tool_combo.currentText()
        current_operation = self._operation_by_tool.get(current_tool, "")
        if current_tool.casefold() == active_tool.casefold():
            current_operation = str(active_operation or current_operation)
        return {
            "version": 2,
            "global": {
                "machine": self.machine_combo.currentText(),
                "material": self.material_combo.currentText(),
                "custom_material": self.custom_material.text().strip(),
                "hardness_hrc": self.hardness.value(),
                "tool_type": self.tool_combo.currentText(),
                "operation": current_operation,
                "model": self.settings.model,
                "reasoning_effort": self.settings.reasoning_effort,
                "mock_mode": self.settings.mock_mode,
            },
            "families": {name: page.values() for name, page in self.pages.items()},
            "operation_by_tool": dict(self._operation_by_tool),
        }

    def _save_calculator_state(self) -> None:
        if not hasattr(self, "pages"):
            return
        try:
            self.settings_service.save_json_setting(
                "last_calculator_state",
                self._calculator_state_payload(),
            )
        except (TypeError, ValueError):
            # State is a convenience; a serialization problem must not stop
            # the calculator from closing or displaying a result.
            return

    def _restore_calculator_state(self) -> None:
        state = self.settings_service.load_json_setting("last_calculator_state", {})
        if not isinstance(state, dict):
            return
        global_state = state.get("global", {})
        if not isinstance(global_state, dict):
            global_state = {}

        model = global_state.get("model")
        if isinstance(model, str) and model in SUPPORTED_MODELS:
            self.settings.model = model
        reasoning_effort = global_state.get("reasoning_effort")
        if isinstance(reasoning_effort, str) and reasoning_effort in {"low", "medium", "high"}:
            self.settings.reasoning_effort = reasoning_effort
        mock_mode = global_state.get("mock_mode")
        if isinstance(mock_mode, bool):
            self.settings.mock_mode = mock_mode
        elif isinstance(mock_mode, str):
            self.settings.mock_mode = mock_mode.strip().casefold() in {"1", "true", "yes", "on"}

        operation_by_tool = state.get("operation_by_tool", {})
        if isinstance(operation_by_tool, dict):
            self._operation_by_tool = {
                str(tool): str(operation)
                for tool, operation in operation_by_tool.items()
                if isinstance(tool, str) and isinstance(operation, str) and operation.strip()
            }

        self._set_combo_casefold(self.machine_combo, global_state.get("machine", ""))
        self._set_combo_casefold(self.material_combo, global_state.get("material", ""))
        tool_type = global_state.get("tool_type", "")
        compatible_type = compatible_tool_type(tool_type) if tool_type else None
        if compatible_type:
            self._set_combo_casefold(self.tool_combo, compatible_type)
        custom_material = global_state.get("custom_material")
        if isinstance(custom_material, str):
            self.custom_material.setText(custom_material)
        try:
            self.hardness.setValue(float(global_state.get("hardness_hrc") or 0))
        except (TypeError, ValueError):
            self.hardness.setValue(0.0)

        families = state.get("families", {})
        if isinstance(families, dict):
            for family, values in families.items():
                if family in self.pages and isinstance(values, dict):
                    self.pages[family].load_values(values)

        # Older state may have kept the current operation only at global
        # level. Family-specific values take precedence when present.
        current_family = tool_family(self.tool_combo.currentText())
        operation = global_state.get("operation")
        if operation and "operation" in self.pages[current_family].fields:
            family_values = families.get(current_family, {}) if isinstance(families, dict) else {}
            if not isinstance(family_values, dict) or "operation" not in family_values:
                self.pages[current_family].load_values({"operation": operation})

    def _save_window_state(self) -> None:
        rect = self.normalGeometry() if self.isMaximized() else self.geometry()
        state = normalise_window_state(
            {
                "x": rect.x(),
                "y": rect.y(),
                "width": rect.width(),
                "height": rect.height(),
                "maximized": self.isMaximized(),
            }
        )
        if state:
            self.settings_service.save_json_setting("last_window_state", state)

    def _restore_window_state(self) -> None:
        state = normalise_window_state(
            self.settings_service.load_json_setting("last_window_state", {})
        )
        if not state:
            return
        screens = QGuiApplication.screens()
        if not screens:
            return
        candidate = QRect(state["x"], state["y"], state["width"], state["height"])
        screen = next(
            (item for item in screens if item.availableGeometry().intersects(candidate)),
            QGuiApplication.primaryScreen() or screens[0],
        )
        available = screen.availableGeometry()
        width = min(max(self.minimumWidth(), candidate.width()), available.width())
        height = min(max(self.minimumHeight(), candidate.height()), available.height())
        x = min(max(candidate.x(), available.left()), available.right() - width + 1)
        y = min(max(candidate.y(), available.top()), available.bottom() - height + 1)
        self.setGeometry(QRect(x, y, width, height))
        if state.get("maximized"):
            self.setWindowState(self.windowState() | Qt.WindowMaximized)

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

    def _tool_changed(self, value: str = "") -> None:
        if not self._restoring_state:
            self._save_calculator_state()
        self._update_tool_page(value)

    def _operation_changed(self, operation: str) -> None:
        if not hasattr(self, "tool_combo"):
            return
        tool_type = self.tool_combo.currentText()
        if tool_type and operation.strip():
            self._operation_by_tool[tool_type] = operation.strip()
        if not self._restoring_state:
            self._save_calculator_state()

        if hasattr(self, "debug_editors"):
            self._reset_result_display()

    def _configure_operation_for_tool(self, tool_type: str) -> None:
        family = tool_family(tool_type)
        page = self.pages[family]
        if "operation" not in page.fields:
            self._active_tool_type = tool_type
            return
        previous_tool = self._active_tool_type
        options = list(operations_for_tool(tool_type))
        current = str(page.values().get("operation", ""))
        remembered = self._operation_by_tool.get(tool_type, "")
        if remembered:
            target = remembered
        elif previous_tool.casefold() == tool_type.casefold() and current:
            target = current
        elif self._restoring_state and is_legacy_operation(current):
            target = current
        else:
            target = default_operation_for_tool(tool_type)
        if target and not any(item.casefold() == target.casefold() for item in options) and is_legacy_operation(target):
            # A legacy value is appended only when reopening old state/history.
            options.append(target)
        # The operation page is shared by several tool types. Set the active
        # identity before changing its combo so the signal cannot save the
        # newly selected tool's operation under the previous tool.
        self._active_tool_type = tool_type
        if options:
            page.set_operation_options(tuple(options), target)
            selected = str(page.values().get("operation", ""))
            if selected:
                self._operation_by_tool[tool_type] = selected

    def _update_tool_page(self, _value: str = "") -> None:
        if not hasattr(self, "tool_combo"):
            return
        tool_type = self.tool_combo.currentText()
        family = tool_family(tool_type)
        self.page_stack.setCurrentWidget(self.pages[family])
        self._configure_operation_for_tool(tool_type)
        if family == "end_mill":
            ball_nose = "ball nose" in tool_type.casefold()
            bull_nose = "bull nose" in tool_type.casefold()
            self.pages[family].set_field_visible("ball_nose_mode", ball_nose)
            self.pages[family].set_field_visible("surface_finish_priority", ball_nose)
            self.pages[family].set_field_visible("ball_nose_contact", ball_nose)
            self.pages[family].set_field_visible("corner_radius_mm", bull_nose)
        if hasattr(self, "result_fields"):
            self._reset_result_display()

    def _machine(self) -> MachineProfile:
        return self.machine_profiles.get(
            self.machine_combo.currentText(),
            MachineProfile("Generic CNC Mill", 12000.0, 10000.0, rigidity="medium"),
        )

    def _collect_request(self) -> MachiningRequest:
        tool_type = self.tool_combo.currentText()
        page = self.pages[tool_family(tool_type)]
        parameters = page.request_values(tool_type)
        operation = str(parameters.pop("operation", tool_type))
        material = self.material_combo.currentText().casefold()
        custom = material == "custom / other"
        hardened = "hardened" in material or material == "toolox 44"
        hardness = self.hardness.value() if (custom or hardened) and self.hardness.value() > 0 else None
        custom_material = self.custom_material.text().strip() if custom else ""
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

    def _load_recent(self) -> None:
        if not hasattr(self, "recent_list"):
            return
        self.recent_list.clear()
        for row in self.database.recent(12):
            try:
                normalized = json.loads(row["normalized_request_json"])
            except json.JSONDecodeError:
                continue
            label = recent_item_text(normalized)
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(0, 47 if "\n" in label else 31))
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
        stored_tool_type = str(normalized.get("tool_type", ""))
        active_tool_type = compatible_tool_type(stored_tool_type)
        if active_tool_type:
            self._set_combo_casefold(self.tool_combo, active_tool_type)
        self.custom_material.setText(normalized.get("custom_material", ""))
        try:
            self.hardness.setValue(float(normalized.get("hardness_hrc") or 0))
        except (TypeError, ValueError):
            self.hardness.setValue(0.0)
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
        self._save_calculator_state()

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
            legacy_warning = legacy_operation_warning(request.tool_type, request.operation)
            if legacy_warning:
                self._show_error(legacy_warning)
                return
            ai_service = self.ai_service or self._reload_ai_service()
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._save_preferences(request)
        self._save_calculator_state()
        self._set_calculating(True)
        self._reset_result_display()
        self.result_status.setText("Calculating machining parameters…")
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
        self._api_error = False
        self._load_recent()
        self._set_calculating(False)
        self._update_status()

    @Slot(object)
    def _calculation_failed(self, message: object) -> None:
        context: dict[str, Any] = {}
        if isinstance(message, dict):
            context = message.get("context", {}) if isinstance(message.get("context", {}), dict) else {}
            message = str(message.get("message", "Calculation failed"))
        else:
            message = str(message)
        self._populate_failure_debug(message, context)
        self._show_error(message)
        self.result_status.setText("Calculation could not be completed")
        if not self.settings.mock_mode and self.settings_service.get_api_key_source() != "none":
            self._api_error = True
        self._set_calculating(False)
        self._update_status()

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

    def _populate_failure_debug(self, message: str, context: dict[str, Any]) -> None:
        """Keep enough safe request/response context to diagnose a rejected run."""

        normalized = context.get("normalized_request", {})
        prompt = str(context.get("prompt", "") or "")
        raw_response = str(context.get("raw_response", "") or "")
        validated_response = str(context.get("validated_response", "") or "")
        self.debug_editors["normalized"].setPlainText(
            json.dumps(normalized, indent=2, ensure_ascii=False, sort_keys=True)
            if normalized
            else "(request was not normalized)"
        )
        self.debug_editors["prompt"].setPlainText(prompt or "(prompt was not generated)")
        self.debug_editors["raw"].setPlainText(raw_response or "(no structured response was received)")
        self.debug_editors["validated"].setPlainText(
            validated_response
            or f"(no validated response was produced)\n\nError:\n{message}"
        )
        metadata = {
            "error": message,
            "stage": context.get("stage", "unknown"),
            "source": context.get("source", ""),
            "request_hash": context.get("request_hash", ""),
            "model": context.get("model", ""),
            "response_id": context.get("response_id", ""),
            "usage": context.get("usage", {}),
        }
        self.debug_editors["meta"].setPlainText(json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True))
        self.debug_button.setChecked(True)
        self.debug_group.setVisible(True)

    # Result display ------------------------------------------------------
    def _apply_result_layout(self, family: str, operation: str = "") -> None:
        layout = result_layout_for_family(family, operation)
        self.result_titles["axial_doc_mm"].setText(layout.axial_title)
        self.result_titles["stepover_mm"].setText(layout.lateral_title)
        self.derived_rows["axial_doc_ratio"][0].setText(layout.axial_title.title())
        self.derived_rows["radial_engagement"][0].setText(layout.lateral_title.title())
        for key, card in self.result_cards.items():
            self.result_key_layout.removeWidget(card)
            card.setVisible(key in layout.primary)
        for index, key in enumerate(layout.primary):
            self.result_key_layout.addWidget(self.result_cards[key], 0, index)
        for column in range(self.result_key_layout.columnCount()):
            self.result_key_layout.setColumnStretch(column, 1 if column < len(layout.primary) else 0)
        for rows, applicable in ((self.info_rows, layout.secondary), (self.derived_rows, layout.derived)):
            for key, (label, value) in rows.items():
                label.setVisible(key in applicable)
                value.setVisible(key in applicable)
        self.primary_group.setVisible(True)
        self.info_group.setVisible(True)
        self.derived_group.setVisible(True)
        self.notes_group.setVisible(True)

    def _reset_result_display(self) -> None:
        self._current_outcome = None
        family = tool_family(self.tool_combo.currentText())
        operation = str(self.pages[family].values().get("operation", ""))
        self._apply_result_layout(family, operation)
        for values in (self.result_fields, self.info_labels, self.derived_labels, self.ai_context_labels):
            for value in values.values():
                value.setText("—")
        self._set_peck_text("—")
        self.result_status.setText("Ready to calculate")
        self.result_banner.setVisible(False)
        self.retry_button.setVisible(False)
        legacy_warning = legacy_operation_warning(self.tool_combo.currentText(), operation)
        if legacy_warning:
            self.result_banner.setText(legacy_warning)
            self.result_banner.setVisible(True)
        self.ai_context_group.setVisible(False)
        self.notes.clear()
        self.notes.setPlaceholderText("AI machining notes and warnings will appear here.")
        for editor in self.debug_editors.values():
            editor.clear()

    def _set_peck_text(self, text: str) -> None:
        value = self.result_fields["peck_mm"]
        value.setText(text)
        value.setWordWrap(True)
        value.setProperty("stateText", text in {"NO PECK", "NOT SPECIFIED", "PECK DATA CONFLICT"})
        value.style().unpolish(value)
        value.style().polish(value)

    def _show_result(self, outcome: CalculationOutcome) -> None:
        self._current_outcome = outcome
        result = outcome.result
        family = tool_family(str(outcome.normalized_request.get("tool_type", self.tool_combo.currentText())))
        operation = str(outcome.normalized_request.get("operation", ""))
        layout = result_layout_for_family(family, operation)
        self._apply_result_layout(family, operation)
        peck_warning = None
        for key in self.result_cards:
            value = getattr(result, key)
            if key == "stepover_mm":
                value = effective_lateral_value(result, layout)
            unit = str(self.result_fields[key].property("unit") or "")
            self.result_fields[key].setText(self._format_value(value, unit))
        if family == "drill":
            peck_text, peck_warning = peck_display(result)
            self._set_peck_text(peck_text)

        secondary: dict[str, str | None] = {
            "cutting_speed": self._format_value(result.cutting_speed_m_min, "m/min")
            if result.cutting_speed_m_min is not None
            else None,
            "feed_per_tooth": self._format_value(result.feed_per_tooth_mm, "mm/tooth")
            if result.feed_per_tooth_mm is not None
            else None,
            "feed_per_rev": self._format_value(result.feed_per_rev_mm, "mm/rev")
            if result.feed_per_rev_mm is not None
            else None,
            "pre_ream_range": result.pre_ream_range_mm.strip()
            if isinstance(result.pre_ream_range_mm, str) and result.pre_ream_range_mm.strip()
            else None,
            "cycle": result.recommended_cycle.strip()
            if isinstance(result.recommended_cycle, str) and result.recommended_cycle.strip()
            else None,
            "coolant": result.coolant.strip() if result.coolant.strip() else None,
            "confidence": result.confidence.strip().title() if result.confidence.strip() else None,
        }
        for key, value in secondary.items():
            self.info_labels[key].setText(value or "—")
        self._show_derived_information(outcome, result, family)

        all_notes = list(result.notes) + list(result.warnings)
        if peck_warning:
            all_notes.append(peck_warning)
        legacy_warning = legacy_operation_warning(str(outcome.normalized_request.get("tool_type", "")), operation)
        if legacy_warning:
            all_notes.append(legacy_warning)
        if "cycle" not in result_layout_for_family(family).secondary and result.recommended_cycle:
            all_notes.append(f"Cycle / method: {result.recommended_cycle}")
        all_notes.extend(f"Local validation: {item}" for item in outcome.validation_corrections)
        notes: list[str] = []
        seen_notes: set[str] = set()
        for note in all_notes:
            clean_note = str(note).strip()
            key = clean_note.casefold()
            if clean_note and key not in seen_notes:
                seen_notes.add(key)
                notes.append(clean_note)
        self.notes.setPlainText("\n".join(notes))
        self.notes.setPlaceholderText("No machining notes or warnings were returned.")

        if outcome.source == "mock":
            banner = "DEVELOPMENT MOCK RESULT — not cached or suitable as production data"
        elif outcome.source == "workshop":
            banner = "SAVED WORKSHOP SETTING — local preference takes priority"
        elif outcome.source == "cache":
            banner = "Cached result — no API request was made"
        else:
            banner = f"AI result from {outcome.model}"
        self.result_banner.setObjectName("resultBanner")
        self.result_banner.setText(banner + (" — " + legacy_warning if legacy_warning else ""))
        self.result_banner.setVisible(True)
        self.retry_button.setVisible(False)
        self._populate_debug(outcome)
        if any("Incompatible Reamer peck data discarded locally" in item for item in outcome.validation_corrections):
            self.debug_button.setChecked(True)

    @staticmethod
    def _parameter_number(parameters: dict[str, Any], *names: str) -> float | None:
        for name in names:
            value = parameters.get(name)
            if value is None or value == "":
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                return number
        return None

    @staticmethod
    def _set_optional_row(
        rows: dict[str, tuple[QLabel, QLabel]],
        key: str,
        value: str | None,
    ) -> bool:
        label, value_widget = rows[key]
        visible = value is not None and bool(str(value).strip())
        label.setVisible(visible)
        value_widget.setVisible(visible)
        value_widget.setText(value if visible else "—")
        return visible

    def _show_derived_information(
        self,
        outcome: CalculationOutcome,
        result: MachiningResult,
        family: str,
    ) -> None:
        request = outcome.normalized_request if isinstance(outcome.normalized_request, dict) else {}
        parameters = request.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        diameter = self._parameter_number(parameters, "diameter_mm", "cutter_diameter_mm")
        depth = self._parameter_number(parameters, "hole_depth_mm")
        machine = self._machine()

        derived: dict[str, str | None] = {
            "hole_ld_ratio": None,
            "radial_engagement": None,
            "axial_doc_ratio": None,
            "mrr": None,
            "rpm_usage": None,
            "feed_usage": None,
            "tap_relationship": None,
        }
        ld = hole_ld_ratio(depth, diameter) if family in {"drill", "reamer"} else None
        if ld is not None:
            derived["hole_ld_ratio"] = f"{ld:.2f}× diameter"

        layout = result_layout_for_family(family, str(request.get("operation", "")))
        lateral = effective_lateral_value(result, layout)
        radial_percent = radial_engagement_percent(lateral, diameter)
        if lateral is not None and radial_percent is not None:
            derived["radial_engagement"] = (
                f"{lateral:.3f} mm ({radial_percent:.1f}% cutter D)"
            )

        axial_ratio = axial_doc_ratio(result.axial_doc_mm, diameter)
        if result.axial_doc_mm is not None and axial_ratio is not None:
            derived["axial_doc_ratio"] = f"{result.axial_doc_mm:.3f} mm ({axial_ratio:.2f}×D)"

        mrr = (
            material_removal_rate_cm3_min(result.axial_doc_mm, lateral, result.feed_mm_min)
            if "mrr" in layout.derived
            else None
        )
        if mrr is not None:
            derived["mrr"] = f"{mrr:.3f} cm³/min"

        rpm_usage_value = usage_percent(result.rpm, machine.max_rpm)
        if result.rpm is not None and rpm_usage_value is not None:
            derived["rpm_usage"] = (
                f"{self._format_value(result.rpm, 'RPM')} / "
                f"{self._format_value(machine.max_rpm, 'RPM')} ({rpm_usage_value:.1f}%)"
            )
        feed_usage_value = usage_percent(result.feed_mm_min, machine.max_feed_mm_min)
        if result.feed_mm_min is not None and feed_usage_value is not None:
            derived["feed_usage"] = (
                f"{self._format_value(result.feed_mm_min, 'mm/min')} / "
                f"{self._format_value(machine.max_feed_mm_min, 'mm/min')} ({feed_usage_value:.1f}%)"
            )

        if family == "tap":
            pitch = result.tap_pitch_mm or self._parameter_number(parameters, "pitch_mm")
            tap_parts: list[str] = []
            if pitch is not None:
                tap_parts.append(f"pitch {pitch:g} mm")
            if result.feed_per_rev_mm is not None:
                tap_parts.append(f"feed/rev {result.feed_per_rev_mm:g} mm")
            if result.rpm is not None:
                tap_parts.append(f"{result.rpm:g} RPM")
            if result.feed_mm_min is not None:
                tap_parts.append(f"feed {result.feed_mm_min:g} mm/min")
            derived["tap_relationship"] = " · ".join(tap_parts) or None

        for key, value in derived.items():
            self.derived_labels[key].setText((value or "—") if key in layout.derived else "—")

        torque = result.estimated_spindle_torque_nm
        if torque is None:
            torque = torque_from_power(result.estimated_spindle_power_kw, result.rpm)
        ai_context: dict[str, str | None] = {
            "engagement_description": result.engagement_description,
            "setup_risk": result.setup_risk.title() if result.setup_risk else None,
            "recommendation_summary": result.recommendation_summary,
            "power": self._format_value(result.estimated_spindle_power_kw, "kW")
            if result.estimated_spindle_power_kw is not None
            else None,
            "torque": self._format_value(torque, "N·m") if torque is not None else None,
        }
        ai_visible = [
            self._set_optional_row(self.ai_context_rows, key, value)
            for key, value in ai_context.items()
        ]
        self.ai_context_group.setVisible(any(ai_visible))

    @staticmethod
    def _format_value(value: float | None, suffix: str) -> str:
        if value is None:
            return "—"
        if abs(value - round(value)) < 1e-8:
            text = f"{value:,.0f}"
        else:
            text = f"{value:,.3f}".rstrip("0").rstrip(".")
        return f"{text} {suffix}"

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
    def _open_about(self) -> None:
        AboutDialog(self).exec()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.database, replace(self.settings), self)
        dialog.connection_test_finished.connect(self._connection_test_finished)
        if dialog.exec() == dialog.Accepted:
            self._reload_settings()

    def _reload_settings(self) -> None:
        """Apply saved settings immediately, including the active AI service."""

        self.settings = self.settings_service.load()
        apply_theme(QApplication.instance(), self.settings.appearance)
        self._api_error = False
        self._refresh_machine_profiles()
        self._reload_ai_service()
        self._update_status()

    def _reload_ai_service(self):
        """Build the current service once so settings changes take effect now."""

        self.ai_service = self._make_ai_service()
        return self.ai_service

    @Slot(object)
    def _connection_test_finished(self, result: ConnectionTestResult) -> None:
        self._api_error = not result.success and result.category not in {"no_key", "mock"}
        self._update_status()

    def _update_status(self) -> None:
        if self.settings.mock_mode:
            text = "MOCK MODE"
            self.status_badge.setObjectName("mockBadge")
            tooltip = "Development/mock mode is active. Results are not production data and are not cached."
        elif self._api_error:
            text = "API ERROR"
            self.status_badge.setObjectName("errorBadge")
            tooltip = "The last OpenAI operation failed. Open Settings to test the connection."
        elif self.settings_service.get_api_key_source() != "none":
            text = f"LIVE AI · {model_display_name(self.settings.model)}"
            self.status_badge.setObjectName("readyBadge")
            tooltip = "Live OpenAI mode is active. The selected model can be changed in Settings."
        else:
            text = "NO API KEY"
            self.status_badge.setObjectName("warningBadge")
            tooltip = "LIVE AI MODE is selected, but no OpenAI API key is configured. Open Settings to add one or enable mock mode."
        no_key = text == "NO API KEY"
        self.status_badge.setText(text)
        self.status_badge.setToolTip(tooltip)
        self.api_status_notice.setText("LIVE AI MODE — No OpenAI API key configured. Open Settings to add one or enable mock mode.")
        self.api_status_notice.setVisible(no_key)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    @staticmethod
    def _set_combo_casefold(widget: QComboBox, value: str) -> None:
        for index in range(widget.count()):
            if widget.itemText(index).casefold() == str(value).casefold():
                widget.setCurrentIndex(index)
                return

    def closeEvent(self, event) -> None:
        self._save_calculator_state()
        self._save_window_state()
        if self._worker:
            self._worker.cancel()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)
        event.accept()


def apply_styles(app: QApplication, appearance: str = "light") -> None:
    """Backward-compatible styling entry point used by the test harness."""

    apply_theme(app, appearance)
