"""Main workshop calculator window."""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QRect, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from ..config.constants import (
    APP_NAME,
    APP_VERSION,
    COATINGS,
    COOLANTS,
    COMPANY_NAME,
    MATERIALS,
    PRODUCT_TAGLINE,
    PUBLISHER_NAME,
    PPT_HORIZONTAL_LOGO_PATH,
    TOOL_TYPES,
    WINDOWS_ICON_PATH,
    compatible_tool_type,
    model_display_name,
    tool_family,
)
from ..config.operations import (
    ENCY_OPERATIONS,
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
from ..services.settings_service import (
    API_KEY_SOURCE_ENVIRONMENT,
    API_KEY_SOURCE_NONE,
    API_KEY_SOURCE_SAVED,
    SettingsService,
)
from ..services.recent_summary import recent_item_text
from ..services.tool_library import ToolLibraryService
from .dialogs import AboutDialog, SettingsDialog
from .tool_library_dialog import AddToolWizard, ToolLibraryDialog, WorkshopFeedbackDialog
from .result_layout import peck_display, result_layout_for_family, effective_lateral_value
from .theme import apply_theme
from .widgets import DrillPage, EndMillPage, FieldPage, IndexablePage, ReamerPage, TapPage, combo, double_spin


class CalculationWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)
    progress = Signal(str)
    done = Signal()

    def __init__(self, calculation_service: CalculationService, request: MachiningRequest, machine: MachineProfile):
        super().__init__()
        self.calculation_service = calculation_service
        self.request = request
        self.machine = machine
        self.cancelled = False
        self.calculation_service.progress_callback = self.progress.emit

    @Slot()
    def run(self) -> None:
        started_at = time.monotonic()
        try:
            outcome = self.calculation_service.calculate(self.request, self.machine)
        except Exception as exc:  # surfaced as a clean status message
            if not self.cancelled:
                self.failed.emit(
                    {
                        "message": str(exc),
                        "context": {
                            **dict(getattr(self.calculation_service, "last_failure_context", {}) or {}),
                            "elapsed_seconds": round(time.monotonic() - started_at, 1),
                        },
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


def _material_accepts_hardness(material: str) -> bool:
    normalized = material.strip().casefold()
    return (
        normalized == "custom / other"
        or "hardened" in normalized
        or normalized == "toolox 44"
    )


OTHER_JOB_TYPE = "Other / describe job"
SURFACE_JOB_TYPE = "3D surface / wall finish"
GUIDED_JOB_TYPES = (
    "Profile / outside contour", "Pocket / cavity", "Slot", "Face / remove stock from top",
    SURFACE_JOB_TYPE, "Drill hole", "Ream hole", "Tap thread", "Thread mill",
    "Chamfer / countersink", OTHER_JOB_TYPE,
)
_MILLING_JOB_TYPES = GUIDED_JOB_TYPES[:5] + (OTHER_JOB_TYPE,)
_JOB_TYPES_BY_TOOL = {
    "drill": ("Drill hole", OTHER_JOB_TYPE),
    "spot drill / centre drill": ("Chamfer / countersink", "Drill hole", OTHER_JOB_TYPE),
    "countersink": ("Chamfer / countersink", OTHER_JOB_TYPE),
    "chamfer mill": ("Chamfer / countersink", OTHER_JOB_TYPE),
    "chamfer tool": ("Chamfer / countersink", OTHER_JOB_TYPE),
    "reamer": ("Ream hole", OTHER_JOB_TYPE),
    "tap": ("Tap thread", OTHER_JOB_TYPE),
    "thread mill": ("Thread mill", OTHER_JOB_TYPE),
    "face mill": ("Face / remove stock from top", OTHER_JOB_TYPE),
    "end mill": _MILLING_JOB_TYPES,
    "ball nose end mill": _MILLING_JOB_TYPES,
    "bull nose / corner radius end mill": _MILLING_JOB_TYPES,
    "indexable end mill": _MILLING_JOB_TYPES,
    "round insert / bull cutter": _MILLING_JOB_TYPES,
}
# Job types offered by earlier releases: (current job type, surface type).
_LEGACY_JOB_TYPES = {
    "3d surface": (SURFACE_JOB_TYPE, "Freeform / 3D"),
    "steep wall / 3d wall finish": (SURFACE_JOB_TYPE, "Steep wall"),
    "flat / land finish": (SURFACE_JOB_TYPE, "Flat land"),
    "open-ended material removal": (OTHER_JOB_TYPE, ""),
}


def guided_job_types_for_tool(tool_type: str) -> tuple[str, ...]:
    """Return the physical jobs a tool can do; an unknown tool offers them all."""

    return _JOB_TYPES_BY_TOOL.get(str(tool_type or "").strip().casefold(), GUIDED_JOB_TYPES)


class MainWindow(QMainWindow):
    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.settings_service = SettingsService(database)
        self.settings = self.settings_service.load()
        self.tool_library = ToolLibraryService(database)
        self.workflow_mode = "guided"
        self._guided_snapshot: dict[str, Any] = {}
        self._restoring_state = True
        self._thread: QThread | None = None
        self._worker: CalculationWorker | None = None
        self._restart_pending = False
        self._current_outcome: CalculationOutcome | None = None
        self._debug_visible = False
        self._api_error = False
        self._progress_stage = "Preparing calculation"
        self._progress_started_at = 0.0
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._update_calculation_progress)
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
        self.selected_model_label = QLabel()
        self.selected_model_label.setObjectName("selectedModelLabel")
        self.selected_model_label.setToolTip("Selected for new live AI requests. Mock mode does not call the AI model.")
        header.addWidget(self.selected_model_label)
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
        restart_row = QHBoxLayout()
        self.model_change_notice = QLabel()
        self.model_change_notice.setObjectName("hint")
        self.model_change_notice.setVisible(False)
        restart_row.addWidget(self.model_change_notice, 1)
        self.restart_app_button = QPushButton("Restart app")
        self.restart_app_button.setVisible(False)
        self.restart_app_button.clicked.connect(self._restart_app)
        restart_row.addWidget(self.restart_app_button)
        root.addLayout(restart_row)
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
        splitter.setSizes([520, 850])
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

        outer.addWidget(workflow)

        mode_row = QHBoxLayout()
        mode_label = QLabel("Workflow")
        self.workflow_combo = QComboBox()
        self.workflow_combo.addItem("AI Guided", "guided")
        self.workflow_combo.addItem("Advanced / Manual", "manual")
        self.workflow_combo.currentIndexChanged.connect(self._workflow_changed)
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.workflow_combo, 1)
        self.recent_button = QPushButton("Recent…")
        self.recent_button.setToolTip("Reopen a recent calculation")
        self.recent_button.clicked.connect(self._open_recent)
        mode_row.addWidget(self.recent_button)
        outer.addLayout(mode_row)

        self.workflow_stack = QStackedWidget()
        self.guided_page = self._build_guided_page()
        self.workflow_stack.addWidget(self.guided_page)

        manual_page = QWidget()
        manual_layout = QVBoxLayout(manual_page)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_tool_group = QGroupBox("Advanced / Manual tool setup")
        manual_tool_form = QFormLayout(manual_tool_group)
        self.tool_combo = QComboBox()
        self._compact_combo(self.tool_combo)
        self.tool_combo.addItems(list(TOOL_TYPES))
        self.tool_combo.setCurrentText(self.settings.last_tool_type)
        self.tool_combo.currentTextChanged.connect(self._tool_changed)
        self.manual_library_combo = QComboBox()
        self._compact_combo(self.manual_library_combo)
        self.manual_library_combo.setToolTip("Fill the tool details below from a Tool Library cutter. Values stay editable.")
        self.manual_library_combo.activated.connect(self._fill_manual_from_library)
        manual_tool_form.addRow("From Tool Library", self.manual_library_combo)
        manual_tool_form.addRow("Tool family", self.tool_combo)
        manual_layout.addWidget(manual_tool_group)

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
        manual_layout.addWidget(page_scroll, 1)
        self.workflow_stack.addWidget(manual_page)
        outer.addWidget(self.workflow_stack, 1)

        # Recent calculations open on demand so the job form keeps the column.
        self.recent_dialog = QDialog(self)
        self.recent_dialog.setWindowTitle("Recent calculations")
        self.recent_dialog.resize(540, 440)
        recent_layout = QVBoxLayout(self.recent_dialog)
        recent_hint = QLabel("Double-click a calculation to reopen its inputs and result.")
        recent_hint.setObjectName("hint")
        recent_layout.addWidget(recent_hint)
        self.recent_list = QListWidget()
        self.recent_list.itemDoubleClicked.connect(self._load_recent_item)
        recent_layout.addWidget(self.recent_list)

        self.independent_check = QCheckBox("Independent AI check (slower, second review)")
        self.independent_check.setChecked(True)
        self.independent_check.setToolTip(
            "Ticked: a second AI request reviews the recommendation before it is shown.\n"
            "Unticked: quicker result from the first AI request only, marked as not cross-checked."
        )
        self.independent_check.toggled.connect(self._independent_check_toggled)
        outer.addWidget(self.independent_check)

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
        self._refresh_guided_tools()
        return panel

    def _build_guided_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 6, 8)
        content_layout.setSpacing(10)

        tool_group = QGroupBox("Workshop tool")
        tool_form = QFormLayout(tool_group)
        self.guided_tool_combo = QComboBox()
        self.guided_tool_combo.setObjectName("guidedToolSelector")
        self._compact_combo(self.guided_tool_combo)
        self.guided_tool_combo.setEditable(True)
        self.guided_tool_combo.setInsertPolicy(QComboBox.NoInsert)
        completer = QCompleter(self.guided_tool_combo.model(), self.guided_tool_combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.guided_tool_combo.setCompleter(completer)
        self.guided_tool_combo.currentIndexChanged.connect(self._guided_tool_changed)
        self.tool_library_button = QPushButton("TOOL LIBRARY")
        self.tool_library_button.clicked.connect(self._open_tool_library)
        tool_row = QWidget()
        tool_row_layout = QHBoxLayout(tool_row)
        tool_row_layout.setContentsMargins(0, 0, 0, 0)
        tool_row_layout.addWidget(self.guided_tool_combo, 1)
        tool_row_layout.addWidget(self.tool_library_button)
        tool_form.addRow("Tool", tool_row)
        self.guided_tool_facts = QLabel("Select a library cutter, or choose a temporary tool.")
        self.guided_tool_facts.setWordWrap(True)
        self.guided_tool_facts.setObjectName("hint")
        tool_form.addRow(self.guided_tool_facts)
        content_layout.addWidget(tool_group)

        self.temporary_tool_group = QGroupBox("Temporary / unsaved tool")
        temporary_form = QFormLayout(self.temporary_tool_group)
        self.temporary_tool_type = QComboBox()
        self.temporary_tool_type.addItems(list(TOOL_TYPES))
        self.temporary_tool_type.currentTextChanged.connect(self._apply_job_type_filter)
        temporary_form.addRow("Tool family", self.temporary_tool_type)
        self.temporary_diameter = double_spin(maximum=500.0, decimals=3, step=0.5)
        temporary_form.addRow("Diameter (mm)", self.temporary_diameter)
        self.temporary_count = double_spin(maximum=100.0, decimals=0, step=1)
        temporary_form.addRow("Flutes / inserts (if known)", self.temporary_count)
        self.temporary_material = QComboBox()
        self.temporary_material.addItems(["Unknown", "Carbide", "HSS", "HSS-Co / Cobalt", "Indexable"])
        temporary_form.addRow("Tool material", self.temporary_material)
        self.temporary_coating = QComboBox()
        self.temporary_coating.addItem("Unknown")
        self.temporary_coating.addItems(list(COATINGS))
        temporary_form.addRow("Coating (if known)", self.temporary_coating)
        self.temporary_manufacturer = QLineEdit()
        temporary_form.addRow("Manufacturer (optional)", self.temporary_manufacturer)
        self.save_temporary_button = QPushButton("SAVE TEMPORARY TOOL TO LIBRARY")
        self.save_temporary_button.clicked.connect(self._save_temporary_tool)
        temporary_form.addRow(self.save_temporary_button)
        self.temporary_tool_group.setVisible(False)
        content_layout.addWidget(self.temporary_tool_group)

        job_group = QGroupBox("Describe the physical job")
        job_form = QFormLayout(job_group)
        self.guided_job_form = job_form
        self.guided_job_type = QComboBox()
        self.guided_job_type.addItems(list(GUIDED_JOB_TYPES))
        self.guided_job_type.currentTextChanged.connect(self._guided_job_changed)
        job_form.addRow("Job type", self.guided_job_type)
        self.guided_job_description = QLineEdit()
        self.guided_job_description.setPlaceholderText("e.g. Profile flame-cut plate")
        job_form.addRow("Job description", self.guided_job_description)
        self.guided_fields: dict[str, QWidget] = {}
        self.guided_rows: dict[str, tuple[QWidget, QWidget]] = {}
        self.guided_row_forms: dict[str, QFormLayout] = {}
        # Essentials stay in the job form; everything that has a sensible
        # remembered value or is optional lives in a collapsed section.
        self.optional_toggle = QPushButton()
        self.optional_toggle.setObjectName("sectionToggle")
        self.optional_toggle.setCheckable(True)
        self.optional_contents = QWidget()
        optional_form = QFormLayout(self.optional_contents)
        optional_form.setContentsMargins(0, 4, 0, 0)
        self.guided_optional_form = optional_form
        target_form = job_form

        def add_text(key: str, label: str, placeholder: str = "") -> QLineEdit:
            widget = QLineEdit()
            widget.setPlaceholderText(placeholder)
            self._add_guided_field(target_form, key, label, widget)
            return widget

        def add_number(key: str, label: str, maximum: float = 5000.0, decimals: int = 3, step: float = 0.5):
            widget = double_spin(maximum=maximum, decimals=decimals, step=step)
            self._add_guided_field(target_form, key, label, widget)
            return widget

        def add_choice(key: str, label: str, choices: tuple[str, ...] | list[str]):
            widget = QComboBox()
            widget.addItems(list(choices))
            self._add_guided_field(target_form, key, label, widget)
            return widget

        self.job_depth = add_number("job_depth_mm", "Required job depth / material thickness (mm)", decimals=2)
        self.stock_on_side = add_number("stock_on_side_mm", "Stock on side (mm)")
        self.stock_to_remove = add_number("stock_to_remove_mm", "Total stock to remove (mm)")
        self.face_width = add_number("face_width_mm", "Approximate face width (mm)")
        self.pocket_depth = add_number("pocket_depth_mm", "Total pocket depth (mm)")
        self.stock_remaining = add_number("stock_remaining_mm", "Stock remaining for 3D finish (mm)")
        self.surface_type = add_choice("surface_type", "Surface type", ["Unknown", "Steep wall", "Shallow surface", "Flat land", "Freeform / 3D"])
        self.finish_requirement = add_choice("finish_requirement", "Finish required", ["Not specified", "Rough only", "Finish only", "Rough + Finish"])
        self.hole_diameter = add_number("hole_diameter_mm", "Required hole diameter (mm)", 1000.0, 3)
        self.hole_depth = add_number("hole_depth_mm", "Hole depth (mm)", 5000.0, 2)
        self.existing_hole = add_number("existing_hole_diameter_mm", "Existing hole diameter (mm)", 1000.0, 3)
        self.thread_size = add_text("thread_size", "Thread size", "e.g. M12")
        self.thread_pitch = add_number("pitch_mm", "Thread pitch (mm)", 25.0, 4, 0.25)
        self.thread_depth = add_number("thread_depth_mm", "Thread depth (mm)", 1000.0, 2)
        target_form = optional_form
        self.open_closed = add_choice("open_closed", "Contour / pocket", ["Not applicable", "Open", "Closed"])
        self.smallest_corner = add_number("smallest_corner_radius_mm", "Smallest internal corner radius (mm)")
        self.entry_access = add_choice("entry_access", "Entry access", ["Unknown", "Open edge", "Predrilled hole", "Plunge access", "Ramp access"])
        self.target_finish_allowance = add_number("target_finish_allowance_mm", "Preferred finish allowance (mm)")
        self.stock_condition = add_choice("stock_condition", "Stock condition", ["Unknown", "Flame-cut", "Saw-cut", "Machined", "Cast / forged"])
        self.guided_coolant = add_choice("coolant_type", "Coolant / lubrication", COOLANTS)
        self.cut_priority = add_choice("cut_priority", "Cut priority", ["Balanced", "Tool life", "Productivity", "Surface finish", "Quiet / low vibration"])
        self.setup_stickout = add_number("stickout_mm", "Actual stickout for this setup (mm)")
        self.setup_rigidity = add_choice("setup_rigidity", "Setup / workholding rigidity", ["Machine profile default", "Very rigid", "Moderate", "Flexible", "Unknown"])
        self.setup_notes = add_text("setup_notes", "Setup notes (optional)", "e.g. Long overhang, thin wall, clamp clearance")
        self.guided_job_group = job_group
        content_layout.addWidget(job_group)

        self.optional_contents.setVisible(False)
        self.optional_toggle.toggled.connect(self._optional_details_toggled)
        self.guided_coolant.currentTextChanged.connect(self._update_optional_summary)
        self.cut_priority.currentTextChanged.connect(self._update_optional_summary)
        self.setup_stickout.valueChanged.connect(self._update_optional_summary)
        optional_group = QGroupBox("Setup details")
        optional_group.setObjectName("secondaryGroup")
        optional_layout = QVBoxLayout(optional_group)
        optional_layout.addWidget(self.optional_toggle)
        optional_layout.addWidget(self.optional_contents)
        optional_group.setToolTip("Remembered between jobs. Change only what differs for this setup.")
        self.guided_optional_group = optional_group
        content_layout.addWidget(optional_group)
        self._update_optional_summary()

        advanced = QGroupBox("ADVANCED OVERRIDES (optional constraints)")
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_layout = QVBoxLayout(advanced)
        advanced_contents = QWidget()
        advanced_contents_layout = QVBoxLayout(advanced_contents)
        advanced_contents_layout.setContentsMargins(0, 0, 0, 0)
        advanced_form = QFormLayout()
        self.guided_advanced_form = advanced_form
        self.guided_advanced_group = advanced
        self.advanced_fields: dict[str, QWidget] = {}

        def advanced_number(key: str, label: str, maximum: float = 100000.0, decimals: int = 3, step: float = 0.5):
            widget = double_spin(maximum=maximum, decimals=decimals, step=step)
            self.advanced_fields[key] = widget
            advanced_form.addRow(label, widget)
            return widget

        advanced_number("max_axial_doc_mm", "Maximum axial DOC (mm)")
        advanced_number("max_radial_engagement_mm", "Maximum radial engagement (mm)")
        advanced_number("max_stepover_mm", "Maximum stepover (mm)")
        advanced_number("max_rpm", "Maximum RPM", 100000.0, 0, 100.0)
        advanced_number("max_feed_mm_min", "Maximum feed (mm/min)", 100000.0, 0, 100.0)
        self.preferred_operation = QComboBox()
        self.preferred_operation.addItem("No preference")
        self.preferred_operation.addItems(list(ENCY_OPERATIONS))
        self.advanced_fields["preferred_operation"] = self.preferred_operation
        advanced_form.addRow("Prefer ENCY operation", self.preferred_operation)
        advanced_number("preferred_finish_allowance_mm", "Preferred finish allowance (mm)")
        self.constraint_full_depth = QCheckBox("Must use full depth")
        self.constraint_one_pass = QCheckBox("Must use one pass")
        self.constraint_avoid_slot = QCheckBox("Avoid full-slot cutting")
        for key, checkbox in (("must_use_full_depth", self.constraint_full_depth), ("must_use_one_pass", self.constraint_one_pass), ("avoid_full_slot", self.constraint_avoid_slot)):
            self.advanced_fields[key] = checkbox
            advanced_form.addRow(checkbox)
        advanced_contents_layout.addLayout(advanced_form)
        advanced_layout.addWidget(advanced_contents)
        advanced_contents.setVisible(False)
        advanced.toggled.connect(advanced_contents.setVisible)
        advanced.setToolTip("Optional limits and preferences; leave blank when you want the AI to choose.")
        content_layout.addWidget(advanced)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self._guided_job_changed(self.guided_job_type.currentText())
        self.guided_tool_combo.addItem("Select a saved tool…", None)
        self.guided_tool_combo.addItem("Temporary / unsaved tool", "temporary")
        return page

    def _add_guided_field(self, form: QFormLayout, key: str, label: str, widget: QWidget) -> None:
        label_widget = QLabel(label)
        label_widget.setWordWrap(True)
        form.addRow(label_widget, widget)
        self.guided_fields[key] = widget
        self.guided_rows[key] = (label_widget, widget)
        self.guided_row_forms[key] = form

    def _optional_details_toggled(self, visible: bool) -> None:
        self.optional_contents.setVisible(visible)
        self._update_optional_summary()

    def _update_optional_summary(self, *_args) -> None:
        if not hasattr(self, "setup_stickout"):
            return
        parts = [self.guided_coolant.currentText(), self.cut_priority.currentText()]
        if self.setup_stickout.value() > 0:
            parts.append(f"stickout {self.setup_stickout.value():g} mm")
        arrow = "▾" if self.optional_toggle.isChecked() else "▸"
        self.optional_toggle.setText(f"{arrow}  {' · '.join(parts)}  (change…)")

    def _guided_tool_type(self) -> str:
        """Tool label of the current Guided selection, or '' when none."""

        value = self.guided_tool_combo.currentData()
        if value == "temporary":
            return self.temporary_tool_type.currentText()
        if value is None:
            return ""
        return str(self._guided_snapshot.get("tool_type") or "")

    def _apply_job_type_filter(self, *_args) -> None:
        """Offer only the jobs the selected tool can do."""

        if not hasattr(self, "guided_rows"):
            return
        allowed = guided_job_types_for_tool(self._guided_tool_type())
        current = self.guided_job_type.currentText()
        existing = tuple(self.guided_job_type.itemText(i) for i in range(self.guided_job_type.count()))
        if existing != allowed:
            self.guided_job_type.blockSignals(True)
            self.guided_job_type.clear()
            self.guided_job_type.addItems(list(allowed))
            self.guided_job_type.setCurrentText(current if current in allowed else allowed[0])
            self.guided_job_type.blockSignals(False)
        self._guided_job_changed(self.guided_job_type.currentText())

    def _refresh_guided_tools(self) -> None:
        if not hasattr(self, "guided_tool_combo"):
            return
        selected = self.guided_tool_combo.currentData()
        self.guided_tool_combo.blockSignals(True)
        self.guided_tool_combo.clear()
        self.guided_tool_combo.addItem("Select a saved tool…", None)
        for tool in self.tool_library.list_tools():
            status = " · NEEDS REVIEW" if tool.get("needs_review") else ""
            self.guided_tool_combo.addItem(str(tool.get("display_name", "Workshop tool")) + status, int(tool["id"]))
        self.guided_tool_combo.addItem("Temporary / unsaved tool", "temporary")
        if hasattr(self, "manual_library_combo"):
            self.manual_library_combo.clear()
            self.manual_library_combo.addItem("Fill from a saved tool…", None)
            for tool in self.tool_library.list_tools():
                self.manual_library_combo.addItem(str(tool.get("display_name", "Workshop tool")), int(tool["id"]))
        target = next((i for i in range(self.guided_tool_combo.count()) if self.guided_tool_combo.itemData(i) == selected), 0)
        self.guided_tool_combo.setCurrentIndex(target)
        self.guided_tool_combo.blockSignals(False)
        self._guided_tool_changed()

    def _fill_manual_from_library(self, _index: int = -1) -> None:
        """Copy a library cutter's known facts into the Advanced / Manual form."""

        tool_id = self.manual_library_combo.currentData()
        snapshot = self.tool_library.tool_snapshot(int(tool_id)) if tool_id is not None else None
        if not snapshot:
            return
        tool_type = compatible_tool_type(str(snapshot.get("tool_type") or ""))
        if tool_type:
            self._set_combo_casefold(self.tool_combo, tool_type)
        insert = snapshot.get("insert") or {}
        diameter = snapshot.get("effective_cutting_diameter_mm") or snapshot.get("diameter_mm")
        facts = {
            "diameter_mm": diameter,
            "cutter_diameter_mm": diameter,
            "flute_count": snapshot.get("flute_count"),
            "insert_count": snapshot.get("insert_count"),
            "tool_material": snapshot.get("tool_material"),
            "coating": snapshot.get("coating"),
            "corner_radius_mm": snapshot.get("corner_radius_mm"),
            "cutting_edge_length_mm": snapshot.get("cutting_edge_length_mm"),
            "stickout_mm": snapshot.get("default_stickout_mm"),
            "insert_code": insert.get("designation"),
            "insert_grade": insert.get("grade"),
        }
        # Unknown library facts leave the existing form values untouched.
        self.pages[tool_family(self.tool_combo.currentText())].load_values(
            {key: value for key, value in facts.items() if value not in (None, "")}
        )
        self._save_calculator_state()

    def _guided_tool_changed(self, _index: int = -1) -> None:
        if not hasattr(self, "guided_tool_combo") or not hasattr(self, "temporary_tool_group"):
            return
        value = self.guided_tool_combo.currentData()
        is_temporary = value == "temporary"
        self.temporary_tool_group.setVisible(is_temporary)
        self._guided_snapshot = {}
        if is_temporary:
            self.guided_tool_facts.setText("Enter only known tool facts. Unknown flute/insert count stays unknown and will be flagged for checking.")
        elif value is None:
            self.guided_tool_facts.setText("Select a workshop cutter, or choose Temporary / unsaved tool. Tool dimensions are read from the library.")
        else:
            snapshot = self.tool_library.tool_snapshot(int(value)) or {}
            self._guided_snapshot = snapshot
            identity = " · ".join(str(part) for part in (snapshot.get("manufacturer"), snapshot.get("product_family")) if part)
            dimensions = []
            if snapshot.get("diameter_mm") is not None:
                dimensions.append(f"Ø{snapshot['diameter_mm']:g} mm")
            if snapshot.get("flute_count"):
                dimensions.append(f"{snapshot['flute_count']} flutes")
            if snapshot.get("insert_count"):
                dimensions.append(f"{snapshot['insert_count']} inserts")
            if snapshot.get("default_stickout_mm") is not None:
                dimensions.append(f"preferred stickout {snapshot['default_stickout_mm']:g} mm")
            insert = snapshot.get("insert") or {}
            insert_text = " · ".join(str(part) for part in (insert.get("designation"), insert.get("grade")) if part)
            if insert_text:
                dimensions.append(insert_text)
            notes = self.tool_library.observations_for_tool(int(value), limit=6)
            suffix = " · NEEDS REVIEW" if snapshot.get("needs_review") or (insert and insert.get("needs_review")) else ""
            note_suffix = f" · {len(notes)} workshop note(s)" if notes else ""
            details = " · ".join(part for part in (identity, ", ".join(dimensions)) if part)
            self.guided_tool_facts.setText((details or "Tool details incomplete") + suffix + note_suffix)
        self._apply_job_type_filter()
        if not self._restoring_state:
            self._save_calculator_state()

    def _guided_job_changed(self, job_type: str = "") -> None:
        if not hasattr(self, "guided_rows"):
            return
        job = str(job_type or "").casefold()
        visible: set[str] = {"coolant_type", "cut_priority", "stock_condition", "stickout_mm", "setup_rigidity", "setup_notes"}
        if "profile" in job:
            visible |= {"job_depth_mm", "stock_on_side_mm", "open_closed", "finish_requirement", "target_finish_allowance_mm", "entry_access"}
            label = "Material thickness / required profile depth (mm)"
            self.guided_rows["job_depth_mm"][0].setText(label)
        elif "pocket" in job:
            visible |= {"pocket_depth_mm", "stock_to_remove_mm", "smallest_corner_radius_mm", "open_closed", "entry_access", "finish_requirement", "target_finish_allowance_mm"}
        elif "face" in job:
            visible |= {"stock_to_remove_mm", "face_width_mm", "finish_requirement", "target_finish_allowance_mm"}
        elif "3d" in job:
            visible |= {"stock_remaining_mm", "surface_type", "finish_requirement", "target_finish_allowance_mm", "entry_access"}
        elif job == "slot":
            visible |= {"job_depth_mm", "stock_on_side_mm", "open_closed", "entry_access", "finish_requirement", "target_finish_allowance_mm"}
            self.guided_rows["job_depth_mm"][0].setText("Required slot depth (mm)")
        elif "drill hole" in job:
            visible |= {"hole_diameter_mm", "hole_depth_mm", "entry_access"}
        elif "ream hole" in job:
            visible |= {"hole_diameter_mm", "hole_depth_mm", "existing_hole_diameter_mm", "entry_access"}
        elif "tap thread" in job or "thread mill" in job:
            visible |= {"thread_size", "pitch_mm", "thread_depth_mm", "hole_diameter_mm", "entry_access"}
        elif "chamfer" in job:
            visible |= {"hole_diameter_mm", "entry_access"}
        else:
            visible |= {"job_depth_mm", "stock_on_side_mm", "stock_to_remove_mm", "open_closed", "finish_requirement", "target_finish_allowance_mm", "entry_access", "surface_type"}
            self.guided_rows["job_depth_mm"][0].setText("Required job depth / thickness (mm)")
        self._visible_guided_fields = visible
        for key, (label, _widget) in self.guided_rows.items():
            self.guided_row_forms[key].setRowVisible(label, key in visible)

        advanced_visible = {"max_rpm", "max_feed_mm_min"}
        if not any(kind in job for kind in ("drill hole", "ream hole", "tap thread", "chamfer")):
            advanced_visible |= {
                "max_axial_doc_mm", "max_radial_engagement_mm", "max_stepover_mm",
                "preferred_finish_allowance_mm",
            }
        if "thread mill" not in job and not any(kind in job for kind in ("drill hole", "ream hole", "tap thread", "chamfer")):
            advanced_visible.add("preferred_operation")
        if any(kind in job for kind in ("profile", "pocket", "slot", "other")):
            advanced_visible |= {"must_use_full_depth", "must_use_one_pass", "avoid_full_slot"}
        self._visible_advanced_fields = advanced_visible
        for key, widget in self.advanced_fields.items():
            self.guided_advanced_form.setRowVisible(widget, key in advanced_visible)
        if not self._restoring_state:
            self._save_calculator_state()
            if hasattr(self, "result_fields") and self.workflow_mode == "guided":
                self._reset_result_display()

    def _workflow_changed(self, _index: int = -1) -> None:
        if not hasattr(self, "workflow_stack"):
            return
        self.workflow_mode = str(self.workflow_combo.currentData() or "guided")
        self.workflow_stack.setCurrentIndex(0 if self.workflow_mode == "guided" else 1)
        if hasattr(self, "independent_check"):
            self.independent_check.setVisible(self.workflow_mode == "guided")
        if not self._restoring_state:
            self._save_calculator_state()
        if hasattr(self, "result_fields"):
            self._reset_result_display()

    def _selected_tool_snapshot(self) -> dict[str, Any]:
        if self.guided_tool_combo.currentIndex() >= 0 and self.guided_tool_combo.currentText() != self.guided_tool_combo.itemText(self.guided_tool_combo.currentIndex()):
            raise ValueError("Choose a saved tool from the matching list entry, or select Temporary / unsaved tool.")
        tool_id = self.guided_tool_combo.currentData()
        if tool_id == "temporary":
            tool_type = self.temporary_tool_type.currentText()
            count = int(self.temporary_count.value()) or None
            family = tool_family(tool_type)
            snapshot = {
                "display_name": "Temporary tool",
                "manufacturer": self.temporary_manufacturer.text().strip(),
                "tool_type": tool_type,
                "diameter_mm": self.temporary_diameter.value() or None,
                "effective_cutting_diameter_mm": None,
                "flute_count": count if family not in {"drill", "reamer", "tap"} else None,
                "insert_count": count if family == "indexable" else None,
                "tool_material": "" if self.temporary_material.currentText() == "Unknown" else self.temporary_material.currentText(),
                "coating": "" if self.temporary_coating.currentText() == "Unknown" else self.temporary_coating.currentText(),
                "product_family": "", "model_code": "", "manufacturer_part_number": "",
                "corner_radius_mm": None, "ball_radius_mm": None, "shank_diameter_mm": None,
                "cutting_edge_length_mm": None, "overall_length_mm": None, "default_stickout_mm": None,
                "approach_angle_deg": None, "hand": "", "holder_interface": "", "notes": "",
                "field_provenance": {}, "confidence": "low", "needs_review": True,
                "revision": 0, "insert": None,
            }
            return snapshot
        if tool_id is None:
            raise ValueError("Select a workshop tool or choose Temporary / unsaved tool.")
        snapshot = self.tool_library.tool_snapshot(int(tool_id))
        if not snapshot:
            raise ValueError("The selected workshop tool could not be found. Refresh the Tool Library and try again.")
        return snapshot

    def _collect_guided_request(self) -> MachiningRequest:
        snapshot = self._selected_tool_snapshot()
        tool_type = str(snapshot.get("tool_type") or "End Mill")
        family = tool_family(tool_type)
        parameters: dict[str, Any] = {
            "diameter_mm": snapshot.get("effective_cutting_diameter_mm") or snapshot.get("diameter_mm"),
            "effective_cutting_diameter_mm": snapshot.get("effective_cutting_diameter_mm"),
            "tool_material": snapshot.get("tool_material") or "Unknown",
            "coating": snapshot.get("coating") or "Unknown",
            "coolant_type": self.guided_coolant.currentText(),
            "job_type": self.guided_job_type.currentText(),
            "cut_priority": self.cut_priority.currentText(),
        }
        for key in ("flute_count", "insert_count", "corner_radius_mm", "ball_radius_mm", "shank_diameter_mm", "cutting_edge_length_mm", "overall_length_mm", "default_stickout_mm", "approach_angle_deg"):
            value = snapshot.get(key)
            if value not in (None, ""):
                parameters[key] = value
        insert = snapshot.get("insert")
        if insert:
            parameters["insert_designation"] = insert.get("designation") or "Unknown"
            parameters["insert_grade"] = insert.get("grade") or "Unknown"
        observations = self.tool_library.observations_for_tool(int(snapshot["library_id"]), limit=8) if snapshot.get("library_id") else []
        if observations:
            parameters["workshop_observations"] = [
                {key: row.get(key) for key in ("category", "note", "actual_rpm", "actual_feed_mm_min", "actual_doc_mm", "actual_engagement_mm") if row.get(key) not in (None, "")}
                for row in observations
            ]
        description = self.guided_job_description.text().strip()
        if description:
            parameters["job_description"] = description
        for key, widget in self.guided_fields.items():
            if key not in self._visible_guided_fields:
                continue
            if isinstance(widget, QDoubleSpinBox):
                value = widget.value()
                if value > 0:
                    parameters[key] = value
            elif isinstance(widget, QComboBox):
                value = widget.currentText().strip()
                if value and value.casefold() not in {"unknown", "not applicable", "not specified"}:
                    parameters[key] = value
            elif isinstance(widget, QLineEdit):
                value = widget.text().strip()
                if value:
                    parameters[key] = value
        if self.guided_job_type.currentText().casefold().startswith("profile") and parameters.get("job_depth_mm"):
            parameters["material_thickness_mm"] = parameters["job_depth_mm"]
        constraints = {}
        if self.guided_advanced_group.isChecked():
            for key, widget in self.advanced_fields.items():
                if key not in self._visible_advanced_fields:
                    continue
                if isinstance(widget, QCheckBox):
                    if widget.isChecked():
                        constraints[key] = True
                elif isinstance(widget, QDoubleSpinBox):
                    if widget.value() > 0:
                        constraints[key] = widget.value()
                elif isinstance(widget, QComboBox) and widget.currentText() != "No preference":
                    constraints[key] = widget.currentText()
        if constraints:
            parameters["constraints"] = constraints
        material = self.material_combo.currentText()
        custom = material.casefold() == "custom / other"
        hardness = (
            self.hardness.value()
            if _material_accepts_hardness(material) and self.hardness.value() > 0
            else None
        )
        return MachiningRequest(
            machine=self.machine_combo.currentText(),
            material=material,
            custom_material=self.custom_material.text().strip() if custom else "",
            hardness_hrc=hardness,
            tool_type=tool_type,
            operation="AI Guided",
            parameters=parameters,
            workflow_mode="guided",
            tool_snapshot=snapshot,
        )

    def _independent_check_toggled(self, _checked: bool = False) -> None:
        if not self._restoring_state:
            self._save_calculator_state()

    def _open_recent(self) -> None:
        self._load_recent()
        self.recent_dialog.show()
        self.recent_dialog.raise_()
        self.recent_dialog.activateWindow()

    def _open_tool_library(self) -> None:
        dialog = ToolLibraryDialog(self.tool_library, self._make_tool_import_service, self, model=self.settings.model)
        dialog.exec()
        self._refresh_guided_tools()

    def _make_tool_import_service(self):
        from ..services.tool_import import ToolImportService

        api_key = self.settings_service.get_active_api_key()
        return ToolImportService(api_key, self.settings.model, self.settings.reasoning_effort)

    def _save_temporary_tool(self) -> None:
        try:
            snapshot = self._selected_tool_snapshot()
        except ValueError as exc:
            QMessageBox.warning(self, "Save tool", str(exc))
            return
        initial = {
            "display_name": f"{snapshot.get('diameter_mm') or ''} mm {snapshot['tool_type']}".strip(),
            "manufacturer": snapshot.get("manufacturer", ""),
            "tool_type": snapshot["tool_type"],
            "diameter_mm": snapshot.get("diameter_mm"),
            "flute_count": snapshot.get("flute_count"),
            "insert_count": snapshot.get("insert_count"),
            "tool_material": snapshot.get("tool_material", ""),
            "coating": snapshot.get("coating", ""),
            "needs_review": True,
            "confidence": "low",
        }
        dialog = AddToolWizard(self.tool_library.list_inserts(), self, initial)
        if dialog.exec() == QDialog.Accepted:
            try:
                saved = self.tool_library.add_tool(dialog.values())
            except Exception as exc:
                QMessageBox.warning(self, "Save tool", str(exc))
                return
            self._refresh_guided_tools()
            index = next((i for i in range(self.guided_tool_combo.count()) if self.guided_tool_combo.itemData(i) == saved["id"]), -1)
            if index >= 0:
                self.guided_tool_combo.setCurrentIndex(index)

    def _record_workshop_feedback(self) -> None:
        outcome = self._current_outcome
        snapshot = outcome.normalized_request.get("tool_snapshot", {}) if outcome else {}
        tool_id = snapshot.get("library_id") if isinstance(snapshot, dict) else None
        if not tool_id:
            QMessageBox.information(self, "Workshop feedback", "Save this temporary tool to the Tool Library before attaching feedback.")
            return
        dialog = WorkshopFeedbackDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        category, note, actuals = dialog.values()
        try:
            self.tool_library.add_observation(int(tool_id), note, category, **actuals)
        except Exception as exc:
            QMessageBox.warning(self, "Workshop feedback", str(exc))
            return
        self.result_status.setText("Workshop observation saved · it will be shown as context only on future calculations")


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
        # A permanent scrollbar keeps the cards from shifting sideways when a
        # result, warning or the Details section makes the content taller.
        result_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
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
        self.what_to_do_group = QGroupBox("WHAT SHOULD I DO?")
        self.what_to_do_group.setObjectName("primaryGroup")
        recommendation_layout = QVBoxLayout(self.what_to_do_group)
        self.recommended_strategy_label = QLabel("The AI machining plan will appear here.")
        self.recommended_strategy_label.setObjectName("resultStrategy")
        self.recommended_strategy_label.setWordWrap(True)
        self.recommended_operation_label = QLabel()
        self.recommended_operation_label.setWordWrap(True)
        self.recommended_operation_label.setObjectName("infoValue")
        recommendation_layout.addWidget(self.recommended_strategy_label)
        recommendation_layout.addWidget(self.recommended_operation_label)
        self.what_to_do_group.setVisible(False)
        outer.addWidget(self.what_to_do_group)
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

        self.pass_plan_group = QGroupBox("Pass plan")
        self.pass_plan_group.setObjectName("secondaryGroup")
        pass_plan_layout = QVBoxLayout(self.pass_plan_group)
        self.pass_plan_table = QTableWidget(0, 7)
        self.pass_plan_table.setHorizontalHeaderLabels(["Stage", "Operation", "Axial step", "Radial / step", "Stock left", "RPM / feed", "Notes"])
        self.pass_plan_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.pass_plan_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.pass_plan_table.setWordWrap(True)
        self.pass_plan_table.verticalHeader().setVisible(False)
        plan_header = self.pass_plan_table.horizontalHeader()
        for column, width in enumerate((115, 130, 95, 110, 95, 125)):
            plan_header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.pass_plan_table.setColumnWidth(column, width)
        plan_header.setSectionResizeMode(6, QHeaderView.Stretch)
        self.pass_plan_table.setMaximumHeight(225)
        pass_plan_layout.addWidget(self.pass_plan_table)
        self.pass_plan_group.setVisible(False)
        outer.addWidget(self.pass_plan_group)

        self.details_button = QPushButton()
        self.details_button.setObjectName("sectionToggle")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_details)
        outer.addWidget(self.details_button)
        self.details_container = QWidget()
        details_layout = QVBoxLayout(self.details_container)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(12)

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
            ("recommended_pass_count", "Recommended pass count"),
            ("recommended_finish_allowance_mm", "Finish allowance"),
            ("recommended_entry_method", "Entry method"),
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
        details_layout.addWidget(info_group)

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
        details_layout.addWidget(self.derived_group)

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
        details_layout.addWidget(notes_group)
        # Optional content follows the stable calculator display.
        details_layout.addWidget(self.ai_context_group)
        outer.addWidget(self.details_container)
        self.key_warnings = QLabel()
        self.key_warnings.setObjectName("keyWarnings")
        self.key_warnings.setWordWrap(True)
        self.key_warnings.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.key_warnings.setVisible(False)
        outer.addWidget(self.key_warnings)
        outer.addWidget(self.result_banner)
        self._toggle_details(False)

        buttons = QHBoxLayout()
        self.retry_button = QPushButton("Retry")
        self.retry_button.setVisible(False)
        self.retry_button.clicked.connect(self._calculate)
        self.debug_button = QPushButton("Show advanced / debug")
        self.debug_button.setCheckable(True)
        self.debug_button.toggled.connect(self._toggle_debug)
        buttons.addWidget(self.retry_button)
        self.feedback_button = QPushButton("Record workshop feedback")
        self.feedback_button.setVisible(False)
        self.feedback_button.clicked.connect(self._record_workshop_feedback)
        buttons.addWidget(self.feedback_button)
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
            ("evidence", "History / research / check"),
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
        for title in ("Normalized", "Request", "Raw", "Validated", "Metadata", "Evidence"):
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
        def widget_value(widget: QWidget):
            if isinstance(widget, QCheckBox):
                return widget.isChecked()
            if isinstance(widget, QComboBox):
                return widget.currentText()
            if isinstance(widget, QDoubleSpinBox):
                return widget.value()
            if isinstance(widget, QLineEdit):
                return widget.text().strip()
            return None

        guided_state = {
            "tool_id": self.guided_tool_combo.currentData(),
            "job_type": self.guided_job_type.currentText(),
            "independent_check": self.independent_check.isChecked(),
            "job_description": self.guided_job_description.text().strip(),
            "fields": {key: widget_value(widget) for key, widget in self.guided_fields.items()},
            "advanced": {key: widget_value(widget) for key, widget in self.advanced_fields.items()},
            "temporary": {
                "tool_type": self.temporary_tool_type.currentText(),
                "diameter_mm": self.temporary_diameter.value(),
                "count": self.temporary_count.value(),
                "tool_material": self.temporary_material.currentText(),
                "coating": self.temporary_coating.currentText(),
                "manufacturer": self.temporary_manufacturer.text().strip(),
            },
        }
        return {
            "version": 3,
            "global": {
                "machine": self.machine_combo.currentText(),
                "material": self.material_combo.currentText(),
                "custom_material": self.custom_material.text().strip(),
                "hardness_hrc": self.hardness.value(),
                "tool_type": self.tool_combo.currentText(),
                "operation": current_operation,
                "workflow_mode": self.workflow_mode,
                "result_details_open": self.details_button.isChecked(),
            },
            "guided": guided_state,
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

        # Model, reasoning and live/mock mode belong to SettingsService.
        # Older calculator snapshots may contain stale copies; never let those
        # override a choice saved in Settings (or a default-model migration).

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

        guided = state.get("guided", {})
        if isinstance(guided, dict):
            job_type = guided.get("job_type")
            legacy_surface = ""
            if isinstance(job_type, str):
                job_type, legacy_surface = _LEGACY_JOB_TYPES.get(job_type.strip().casefold(), (job_type, ""))
                self._set_combo_casefold(self.guided_job_type, job_type)
            self.independent_check.setChecked(bool(guided.get("independent_check", True)))
            description = guided.get("job_description")
            if isinstance(description, str):
                self.guided_job_description.setText(description)
            for collection_name, widgets in (("fields", self.guided_fields), ("advanced", self.advanced_fields)):
                entries = guided.get(collection_name, {})
                if not isinstance(entries, dict):
                    continue
                for key, value in entries.items():
                    widget = widgets.get(key)
                    if widget is None or value is None:
                        continue
                    if isinstance(widget, QCheckBox):
                        widget.setChecked(bool(value))
                    elif isinstance(widget, QComboBox):
                        self._set_combo_casefold(widget, str(value))
                    elif isinstance(widget, QDoubleSpinBox):
                        try:
                            widget.setValue(float(value))
                        except (TypeError, ValueError):
                            pass
                    elif isinstance(widget, QLineEdit):
                        widget.setText(str(value))
            if legacy_surface and self.surface_type.currentText() == "Unknown":
                self._set_combo_casefold(self.surface_type, legacy_surface)
            temporary = guided.get("temporary", {})
            if isinstance(temporary, dict):
                self._set_combo_casefold(self.temporary_tool_type, str(temporary.get("tool_type", "")))
                self._set_combo_casefold(self.temporary_material, str(temporary.get("tool_material", "")))
                self._set_combo_casefold(self.temporary_coating, str(temporary.get("coating", "")))
                self.temporary_manufacturer.setText(str(temporary.get("manufacturer", "")))
                for key, widget in (("diameter_mm", self.temporary_diameter), ("count", self.temporary_count)):
                    try:
                        widget.setValue(float(temporary.get(key) or 0))
                    except (TypeError, ValueError):
                        pass
            tool_id = guided.get("tool_id")
            tool_index = next((i for i in range(self.guided_tool_combo.count()) if self.guided_tool_combo.itemData(i) == tool_id), -1)
            if tool_index >= 0:
                self.guided_tool_combo.setCurrentIndex(tool_index)

        workflow_mode = str(global_state.get("workflow_mode", "guided"))
        mode_index = self.workflow_combo.findData(workflow_mode)
        self.workflow_combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        self.details_button.setChecked(bool(global_state.get("result_details_open", False)))
        self._apply_job_type_filter()

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
        show_hardness = _material_accepts_hardness(material)
        self.custom_material.setVisible(custom)
        self.custom_material.parentWidget().layout().labelForField(self.custom_material).setVisible(custom)  # type: ignore[union-attr]
        hardness_label = self.hardness.parentWidget().layout().labelForField(self.hardness)  # type: ignore[union-attr]
        self.hardness.setVisible(show_hardness)
        hardness_label.setVisible(show_hardness)
        if not show_hardness and self.hardness.value() != 0:
            self.hardness.setValue(0.0)

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
        if self.workflow_mode == "guided":
            return self._collect_guided_request()
        tool_type = self.tool_combo.currentText()
        page = self.pages[tool_family(tool_type)]
        parameters = page.request_values(tool_type)
        operation = str(parameters.pop("operation", tool_type))
        material = self.material_combo.currentText()
        custom = material.casefold() == "custom / other"
        hardness = (
            self.hardness.value()
            if _material_accepts_hardness(material) and self.hardness.value() > 0
            else None
        )
        custom_material = self.custom_material.text().strip() if custom else ""
        return MachiningRequest(
            machine=self.machine_combo.currentText(),
            material=self.material_combo.currentText(),
            custom_material=custom_material,
            hardness_hrc=hardness,
            tool_type=tool_type,
            operation=operation,
            parameters=parameters,
            workflow_mode="manual",
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
            label = recent_item_text(normalized, row.get("model", ""))
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
        guided = str(normalized.get("workflow_mode", "")) == "guided"
        self.workflow_combo.setCurrentIndex(self.workflow_combo.findData("guided" if guided else "manual"))
        self._set_combo_casefold(self.machine_combo, normalized.get("machine", ""))
        self._set_combo_casefold(self.material_combo, normalized.get("material", ""))
        self.custom_material.setText(normalized.get("custom_material", ""))
        try:
            self.hardness.setValue(float(normalized.get("hardness_hrc") or 0))
        except (TypeError, ValueError):
            self.hardness.setValue(0.0)
        if guided:
            self._load_guided_inputs(normalized)
        else:
            stored_tool_type = str(normalized.get("tool_type", ""))
            active_tool_type = compatible_tool_type(stored_tool_type)
            if active_tool_type:
                self._set_combo_casefold(self.tool_combo, active_tool_type)
            page = self.pages[tool_family(self.tool_combo.currentText())]
            page_values = dict(normalized.get("parameters", {}))
            if "operation" in page.fields:
                page_values["operation"] = normalized.get("operation", page_values.get("operation", ""))
            page.load_values(page_values)
        outcome = CalculationOutcome(
            result=result,
            normalized_request=normalized,
            request_hash=row["request_hash"],
            source=row.get("source") or "cache",
            cache_hit=True,
            model=row.get("model") or "Model not recorded",
            validated_response=json.dumps(result.to_dict(), indent=2),
        )
        self._show_result(outcome)
        self.recent_dialog.hide()
        self.result_status.setText("Reopened recent calculation")
        self._save_calculator_state()

    def _load_guided_inputs(self, normalized: dict[str, Any]) -> None:
        """Refill the Guided form from a stored Guided request."""

        parameters = normalized.get("parameters", {})
        parameters = parameters if isinstance(parameters, dict) else {}
        snapshot = normalized.get("tool_snapshot", {})
        snapshot = snapshot if isinstance(snapshot, dict) else {}

        def number(value: Any) -> float:
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0

        def set_widget(widget: QWidget, value: Any) -> None:
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(number(value))
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)
                if value not in (None, ""):
                    self._set_combo_casefold(widget, str(value))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value or ""))

        library_id = snapshot.get("library_id")
        index = self.guided_tool_combo.findData(int(library_id)) if library_id else -1
        if index < 0:
            # The cutter was temporary or has since left the library.
            index = self.guided_tool_combo.findData("temporary")
            self._set_combo_casefold(self.temporary_tool_type, str(snapshot.get("tool_type") or normalized.get("tool_type", "")))
            self.temporary_diameter.setValue(number(snapshot.get("diameter_mm") or parameters.get("diameter_mm")))
            self.temporary_count.setValue(number(snapshot.get("insert_count") or snapshot.get("flute_count")))
            self._set_combo_casefold(self.temporary_material, str(snapshot.get("tool_material") or "Unknown"))
            self._set_combo_casefold(self.temporary_coating, str(snapshot.get("coating") or "Unknown"))
            self.temporary_manufacturer.setText(str(snapshot.get("manufacturer") or ""))
        self.guided_tool_combo.setCurrentIndex(index)
        self._guided_tool_changed()

        job_type = str(parameters.get("job_type", ""))
        job_type, legacy_surface = _LEGACY_JOB_TYPES.get(job_type.strip().casefold(), (job_type, ""))
        self._set_combo_casefold(self.guided_job_type, job_type)
        self.guided_job_description.setText(str(parameters.get("job_description", "")))
        for key, widget in self.guided_fields.items():
            # Fields hidden for this job keep whatever was entered earlier.
            if key in parameters or key in self._visible_guided_fields:
                set_widget(widget, parameters.get(key))
        if legacy_surface and "surface_type" not in parameters:
            self._set_combo_casefold(self.surface_type, legacy_surface)
        constraints = parameters.get("constraints", {})
        constraints = constraints if isinstance(constraints, dict) else {}
        self.guided_advanced_group.setChecked(bool(constraints))
        if constraints:
            for key, widget in self.advanced_fields.items():
                set_widget(widget, constraints.get(key))

    # Calculation lifecycle ----------------------------------------------
    def _make_ai_service(self):
        if self.settings.mock_mode:
            return MockOpenAIService(self.settings.model, self.settings.reasoning_effort)
        api_key = self.settings_service.get_active_api_key()
        if not api_key:
            # The calculation service checks SQLite before calling this object,
            # so a cached/workshop result remains available offline.
            return UnavailableOpenAIService(self.settings.model)
        return OpenAIService(api_key, self.settings.model, self.settings.reasoning_effort)

    def _calculate(self) -> None:
        if self._thread is not None:
            if self._worker is not None and self._worker.cancelled:
                self._restart_pending = True
                self.result_status.setText("Restart queued — waiting for the cancelled request to finish…")
                self.calculate_button.setEnabled(False)
                self.retry_button.setEnabled(False)
            return
        try:
            request = self._collect_request()
            legacy_warning = "" if request.workflow_mode == "guided" else legacy_operation_warning(request.tool_type, request.operation)
            if legacy_warning:
                self._show_error(legacy_warning)
                return
            ai_service = self.ai_service or self._reload_ai_service()
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._save_preferences(request)
        self._save_calculator_state()
        self.calculate_button.setText("CALCULATE")
        self.retry_button.setText("Retry")
        self._set_calculating(True)
        self._reset_result_display()
        self._progress_stage = "Preparing calculation"
        self._progress_started_at = time.monotonic()
        self._progress_timer.start()
        self._update_calculation_progress()
        worker_service = CalculationService(self.database, ai_service)
        worker_service.independent_check = self.independent_check.isChecked()
        self._thread = QThread(self)
        self._worker = CalculationWorker(worker_service, request, self._machine())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._calculation_finished)
        self._worker.failed.connect(self._calculation_failed)
        self._worker.progress.connect(self._calculation_progress)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._calculation_thread_finished)
        self._thread.start()

    def _set_calculating(self, calculating: bool) -> None:
        if not calculating:
            self._progress_timer.stop()
        self.calculate_button.setEnabled(not calculating)
        self.cancel_button.setEnabled(calculating)
        self.machine_combo.setEnabled(not calculating)
        self.material_combo.setEnabled(not calculating)
        self.tool_combo.setEnabled(not calculating)

    @Slot(str)
    def _calculation_progress(self, stage: str) -> None:
        if self._worker is not None and not self._worker.cancelled:
            self._progress_stage = stage
            self._update_calculation_progress()

    def _update_calculation_progress(self) -> None:
        if self._progress_timer.isActive():
            elapsed = max(0, int(time.monotonic() - self._progress_started_at))
            extra = " · Taking longer than usual" if elapsed >= 60 else ""
            self.result_status.setText(f"{self._progress_stage} · {elapsed}s elapsed{extra}")

    def _cancel_calculation(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._restart_pending = False
        self.result_status.setText("Calculation cancelled — choose Restart calculation to run again")
        self._set_calculating(False)
        self.calculate_button.setText("RESTART CALCULATION")
        self.retry_button.setText("Restart calculation")
        self.retry_button.setVisible(True)

    @Slot(object)
    def _calculation_finished(self, outcome: CalculationOutcome) -> None:
        if self._worker is not None and self._worker.cancelled:
            return
        self._show_result(outcome)
        self.result_status.setText("Calculation ready")
        self._api_error = False
        self._load_recent()
        self._set_calculating(False)
        self._update_status()

    @Slot(object)
    def _calculation_failed(self, message: object) -> None:
        if self._worker is not None and self._worker.cancelled:
            return
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
        if self._restart_pending:
            self._restart_pending = False
            self.calculate_button.setEnabled(True)
            self.retry_button.setEnabled(True)
            self._calculate()

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
            "elapsed_seconds": context.get("elapsed_seconds"),
            "source": context.get("source", ""),
            "request_hash": context.get("request_hash", ""),
            "model": context.get("model", ""),
            "response_id": context.get("response_id", ""),
            "usage": context.get("usage", {}),
            "research_status": context.get("research_status", ""),
            "research_sources": context.get("research_sources", []),
            "verification_status": context.get("verification_status", ""),
            "verification_error": context.get("verification_error", ""),
            "verification_findings": context.get("verification_findings", []),
        }
        self.debug_editors["meta"].setPlainText(json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True))
        evidence = {
            "comparison_history": normalized.get("comparison_history", []) if isinstance(normalized, dict) else [],
            "verification_prompt": context.get("verification_prompt", ""),
            "verification_raw_response": context.get("verification_raw_response", ""),
        }
        self.debug_editors["evidence"].setPlainText(json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True))
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
        guided = self.workflow_mode == "guided"
        if guided:
            # The placeholder follows the selected cutter (or the job when no
            # cutter is chosen yet), not the hidden Advanced / Manual page.
            job = self.guided_job_type.currentText().casefold()
            tool_type = self._guided_tool_type()
            if tool_type:
                family = tool_family(tool_type)
            else:
                family = next(
                    (name for marker, name in (("drill hole", "drill"), ("ream", "reamer"), ("tap thread", "tap")) if marker in job),
                    "end_mill",
                )
            operation = ""
        else:
            family = tool_family(self.tool_combo.currentText())
            operation = str(self.pages[family].values().get("operation", ""))
        self._apply_result_layout(family, operation)
        self._has_key_warnings = False
        self.key_warnings.setVisible(False)
        for values in (self.result_fields, self.info_labels, self.derived_labels, self.ai_context_labels):
            for value in values.values():
                value.setText("—")
        self._set_peck_text("—")
        self.what_to_do_group.setVisible(False)
        self.recommended_strategy_label.setText("The AI machining plan will appear here.")
        self.recommended_operation_label.clear()
        self.pass_plan_table.setRowCount(0)
        self.pass_plan_group.setVisible(False)
        self.feedback_button.setVisible(False)
        self.result_status.setText("Ready to calculate")
        self.result_banner.setVisible(False)
        self.retry_button.setVisible(False)
        legacy_warning = "" if guided else legacy_operation_warning(self.tool_combo.currentText(), operation)
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
        self.result_status.setText("Calculation ready")
        self._current_outcome = outcome
        result = outcome.result
        family = tool_family(str(outcome.normalized_request.get("tool_type", self.tool_combo.currentText())))
        operation = str(outcome.normalized_request.get("operation", ""))
        layout = result_layout_for_family(family, operation)
        self._apply_result_layout(family, operation)
        is_guided = str(outcome.normalized_request.get("workflow_mode", "")) == "guided"
        strategy = result.recommended_strategy or result.recommendation_summary or ""
        if is_guided and not strategy:
            strategy = "AI strategy not specified — verify before cutting."
        operation_text = result.recommended_operation or (operation if not is_guided else "Not specified — verify before cutting")
        entry_text = result.recommended_entry_method
        self.recommended_strategy_label.setText(strategy or "Recommendation summary not supplied.")
        self.recommended_operation_label.setText("Recommended operation: " + operation_text + (f"\nEntry: {entry_text}" if entry_text else ""))
        self.what_to_do_group.setVisible(is_guided or bool(strategy) or bool(result.recommended_operation))
        plan = result.pass_plan if isinstance(result.pass_plan, list) else []
        self.pass_plan_table.setRowCount(len(plan))
        for row, stage in enumerate(plan):
            axial = self._format_value(stage.get("axial_doc_mm"), "mm")
            lateral_parts = []
            if stage.get("radial_engagement_mm") is not None:
                lateral_parts.append("Radial " + self._format_value(stage.get("radial_engagement_mm"), "mm"))
            if stage.get("stepover_mm") is not None:
                lateral_parts.append("Step " + self._format_value(stage.get("stepover_mm"), "mm"))
            if stage.get("passes"):
                stage_title = f"{stage.get('stage', '')} · {stage['passes']} {'pass' if stage['passes'] == 1 else 'passes'}"
            else:
                stage_title = str(stage.get("stage", ""))
            values = (
                stage_title,
                str(stage.get("operation") or "—"),
                axial,
                " · ".join(lateral_parts) or "—",
                self._format_value(stage.get("stock_to_leave_mm"), "mm"),
                " / ".join(part for part in (self._format_value(stage.get("rpm"), "RPM"), self._format_value(stage.get("feed_mm_min"), "mm/min")) if part != "—"),
                str(stage.get("notes") or ""),
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.pass_plan_table.setItem(row, col, item)
        self.pass_plan_group.setVisible(bool(plan))
        self.pass_plan_table.resizeRowsToContents()
        self.feedback_button.setVisible(bool((outcome.normalized_request.get("tool_snapshot") or {}).get("library_id")))
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
            "recommended_pass_count": str(result.recommended_pass_count) if result.recommended_pass_count else None,
            "recommended_finish_allowance_mm": self._format_value(result.recommended_finish_allowance_mm, "mm") if result.recommended_finish_allowance_mm is not None else None,
            "recommended_entry_method": result.recommended_entry_method.strip() if result.recommended_entry_method else None,
        }
        for key, value in secondary.items():
            self.info_labels[key].setText(value or "—")
        self._show_derived_information(outcome, result, family)

        all_notes = list(result.notes) + list(result.warnings)
        if result.verification_summary:
            all_notes.append(
                "Independent AI cross-check (not a safety certification): "
                + result.verification_summary
            )
        all_notes.extend("Nearby-history comparison: " + item for item in result.history_comparison)
        all_notes.extend("Cross-check finding: " + item for item in result.verification_findings)
        for source in result.research_sources:
            if not isinstance(source, dict):
                continue
            source_title = str(source.get("title", "")).strip() or "Web source"
            source_url = str(source.get("url", "")).strip()
            if source_url:
                all_notes.append(f"Research source: {source_title} — {source_url}")
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
        key_items, hidden_count = self._key_warnings(
            list(result.warnings) + ([peck_warning] if peck_warning else []) + ([legacy_warning] if legacy_warning else [])
        )
        if key_items:
            more = f"\n+ {hidden_count} more under Details" if hidden_count else ""
            self.key_warnings.setText("\n".join("⚠  " + item for item in key_items) + more)
        # With Details open the full notes are on screen, so do not repeat them.
        self._has_key_warnings = bool(key_items)
        self.key_warnings.setVisible(self._has_key_warnings and not self.details_button.isChecked())

        if outcome.source == "mock":
            model_name = model_display_name(outcome.model)
            banner = (
                f"DEVELOPMENT MOCK RESULT · {model_name} selected — "
                "not cached or suitable as production data"
            )
        elif outcome.source == "workshop":
            banner = "SAVED WORKSHOP SETTING — local preference takes priority"
        elif outcome.source == "cache":
            banner = "Cached result — no API request was made"
        else:
            banner = f"AI result from {model_display_name(outcome.model)}"
        verification_labels = {
            "cross_checked": "AI cross-check completed",
            "review_required": "REVIEW REQUIRED",
            "check_incomplete": "cross-check incomplete",
        }
        if is_guided and result.verification_status in verification_labels:
            banner += " · " + verification_labels[result.verification_status]
        elif is_guided and outcome.source in {"ai", "cache"}:
            banner += " · quick result, not cross-checked"
        if is_guided and result.research_sources:
            banner += f" · {len(result.research_sources)} web source(s)"
        requires_review = is_guided and result.verification_status in {"review_required", "check_incomplete"}
        self.result_banner.setObjectName("reviewBanner" if requires_review else "resultBanner")
        self.result_banner.setText(banner + (" — " + legacy_warning if legacy_warning else ""))
        self.result_banner.setVisible(True)
        self.result_banner.style().unpolish(self.result_banner)
        self.result_banner.style().polish(self.result_banner)
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
            "research_status": outcome.result.research_status,
            "research_sources": outcome.result.research_sources,
            "verification_status": outcome.result.verification_status,
            "verification_summary": outcome.result.verification_summary,
            "verification_findings": outcome.result.verification_findings,
            "verification_response_id": outcome.result.verification_response_id,
        }
        self.debug_editors["meta"].setPlainText(json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True))
        evidence = {
            "comparison_history": outcome.normalized_request.get("comparison_history", []),
            "history_comparison": outcome.result.history_comparison,
            "research_status": outcome.result.research_status,
            "research_sources": outcome.result.research_sources,
            "verification_status": outcome.result.verification_status,
            "verification_summary": outcome.result.verification_summary,
            "verification_findings": outcome.result.verification_findings,
            "verification_prompt": outcome.verification_prompt,
            "verification_raw_response": outcome.verification_raw_response,
        }
        self.debug_editors["evidence"].setPlainText(json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True))

    def _toggle_details(self, visible: bool) -> None:
        self.details_container.setVisible(visible)
        if hasattr(self, "key_warnings"):
            self.key_warnings.setVisible(getattr(self, "_has_key_warnings", False) and not visible)
        self.details_button.setText(
            "▾  Hide details" if visible else "▸  Details — cutting data, derived values, notes and sources"
        )
        if not self._restoring_state:
            self._save_calculator_state()

    @staticmethod
    def _key_warnings(warnings: list[str], limit: int = 3) -> tuple[list[str], int]:
        """Pick the warnings an operator must see; the rest stay in Details."""

        def priority(text: str) -> int:
            lowered = text.casefold()
            if "independent check" in lowered or "unverified" in lowered:
                return 0
            if "locally" in lowered or "conflict" in lowered:
                return 1
            return 2

        unique = list(dict.fromkeys(item.strip() for item in warnings if item and item.strip()))
        ordered = sorted(unique, key=priority)
        return ordered[:limit], max(0, len(ordered) - limit)

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
        if dialog.exec() == QDialog.Accepted:
            self._reload_settings()
            self.model_change_notice.setText(
                f"Settings saved. Selected model: {model_display_name(self.settings.model)}. "
                "New live AI calculations use it now; restart the app if you want a fresh session."
            )
            self.model_change_notice.setVisible(True)
            self.restart_app_button.setVisible(True)
            if getattr(dialog, "restart_requested", False):
                self._restart_app()

    def _restart_app(self) -> None:
        if self._thread is not None:
            QMessageBox.information(self, "Restart CutData AI", "Wait for the current calculation to finish before restarting.")
            return
        self._save_calculator_state()
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        started, _pid = QProcess.startDetached(sys.executable, args, str(Path.cwd()))
        if not started:
            QMessageBox.warning(self, "Restart CutData AI", "The app could not restart automatically. Close and reopen it manually.")
            return
        QApplication.instance().quit()

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
        source = self.settings_service.get_active_api_key_source()
        source_label = {
            API_KEY_SOURCE_ENVIRONMENT: "ENV KEY",
            API_KEY_SOURCE_SAVED: "SAVED KEY",
        }.get(source, "")
        compact_model = model_display_name(self.settings.model).upper()
        self.selected_model_label.setText(f"MODEL: {compact_model}")
        if self.settings.mock_mode:
            text = "MOCK MODE"
            self.status_badge.setObjectName("mockBadge")
            tooltip = "Development/mock mode is active. Results are not production data and are not cached."
        elif self._api_error:
            text = f"API ERROR · {source_label}" if source_label else "API ERROR"
            self.status_badge.setObjectName("errorBadge")
            tooltip = "The last OpenAI operation failed. Open Settings to test the connection."
        elif source != API_KEY_SOURCE_NONE:
            text = f"LIVE AI · {compact_model} · {source_label}"
            self.status_badge.setObjectName("readyBadge")
            tooltip = "Live OpenAI mode is active from the selected key source. Authentication is not implied by this status."
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
