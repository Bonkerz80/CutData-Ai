"""Reusable Qt widgets for the compact, field-driven calculator UI."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)


def combo(values: list[str] | tuple[str, ...], editable: bool = False) -> QComboBox:
    widget = QComboBox()
    widget.addItems(list(values))
    widget.setEditable(editable)
    if editable:
        widget.setInsertPolicy(QComboBox.NoInsert)
    return widget


def double_spin(
    value: float = 0.0,
    maximum: float = 100000.0,
    decimals: int = 3,
    step: float = 0.1,
) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(0.0, maximum)
    widget.setDecimals(decimals)
    widget.setSingleStep(step)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setAlignment(Qt.AlignRight)
    return widget


def integer_spin(value: int = 0, maximum: int = 100) -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(0, maximum)
    widget.setValue(value)
    widget.setAlignment(Qt.AlignRight)
    return widget


class ModeSwitch(QPushButton):
    """A prominent, keyboard-friendly switch for mock versus live mode."""

    def __init__(self, mock_mode: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("modeSwitch")
        self.setCheckable(True)
        self.setMinimumHeight(36)
        self.setMinimumWidth(160)
        self.setAccessibleName("Development / mock mode")
        self.setToolTip("When enabled, calculations use offline development data and are never cached.")
        self.toggled.connect(self._update_label)
        self.setChecked(mock_mode)
        self._update_label(mock_mode)

    def _update_label(self, mock_mode: bool) -> None:
        self.setText("MOCK MODE ON" if mock_mode else "LIVE AI MODE")


class FieldPage(QWidget):
    """Form page that exposes its values as a plain dictionary."""

    operation_changed = Signal(str)

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.title = title
        self.fields: dict[str, QWidget] = {}
        self.rows: dict[str, tuple[QWidget, QWidget]] = {}
        self.form = QFormLayout(self)
        self.form.setContentsMargins(18, 10, 18, 18)
        self.form.setHorizontalSpacing(20)
        self.form.setVerticalSpacing(11)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

    def add_heading(self, text: str) -> None:
        heading = QLabel(text.upper())
        heading.setObjectName("formHeading")
        self.form.addRow(heading)

    def add_field(self, key: str, label: str, widget: QWidget) -> QWidget:
        label_widget = QLabel(label)
        self.form.addRow(label_widget, widget)
        self.fields[key] = widget
        self.rows[key] = (label_widget, widget)
        return widget

    def add_hint(self, text: str) -> None:
        hint = QLabel(text)
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        self.form.addRow(hint)

    def set_field_visible(self, key: str, visible: bool) -> None:
        if key not in self.rows:
            return
        label, widget = self.rows[key]
        label.setVisible(visible)
        widget.setVisible(visible)

    def values(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QComboBox):
                result[key] = widget.currentText().strip()
            elif isinstance(widget, QCheckBox):
                result[key] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                result[key] = widget.text().strip()
            elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                result[key] = widget.value()
        return result

    def load_values(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            widget = self.fields.get(key)
            if widget is None or value is None:
                continue
            if isinstance(widget, QComboBox):
                index = next(
                    (candidate for candidate in range(widget.count()) if widget.itemText(candidate).casefold() == str(value).casefold()),
                    -1,
                )
                if index >= 0:
                    widget.setCurrentIndex(index)
                elif widget.isEditable():
                    widget.setCurrentText(str(value))
            elif isinstance(widget, QCheckBox):
                if isinstance(value, str):
                    widget.setChecked(value.strip().casefold() in {"1", "true", "yes", "on"})
                else:
                    widget.setChecked(bool(value))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))
            elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                try:
                    widget.setValue(float(value))
                except (TypeError, ValueError):
                    pass


class DrillPage(FieldPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__("Drill", parent)
        self.add_heading("Drill details")
        self.add_field("diameter_mm", "Diameter (mm)", double_spin(10.0))
        self.add_field("tool_material", "Tool material", combo(("HSS", "HSS-Co / Cobalt", "Carbide", "Indexable")))
        self.add_field("coating", "Coating", combo(("Uncoated", "TiN", "TiCN", "TiAlN", "AlTiN", "Other")))
        self.add_field("hole_depth_mm", "Hole depth (mm)", double_spin(20.0, step=0.1))
        self.add_field("material_thickness_mm", "Material thickness (mm)", double_spin(25.0, step=0.1))
        self.add_field("hole_type", "Hole", combo(("Through hole", "Blind hole")))
        self.add_field("existing_pilot_hole_diameter_mm", "Pilot hole (mm, optional)", double_spin(0.0, step=0.1))
        self.add_field("flute_length_mm", "Flute length (mm, optional)", double_spin(0.0, step=0.1))
        self.add_field("chip_evacuation", "Chip evacuation", combo(("Not specified", "Good", "Restricted", "Deep-hole concern")))
        self.add_heading("Coolant")
        internal = QCheckBox("Internal / through-tool coolant")
        flood = QCheckBox("Flood coolant")
        flood.setChecked(True)
        self.add_field("internal_coolant", "", internal)
        self.add_field("flood_coolant", "", flood)
        self.add_hint("All dimensions accept direct keyboard entry. A value of 0 means optional/not supplied.")


class ReamerPage(FieldPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__("Reamer", parent)
        self.add_heading("Reamer details")
        self.add_field("diameter_mm", "Reamer diameter (mm)", double_spin(10.0))
        self.add_field("tool_material", "Tool material", combo(("HSS", "Carbide")))
        self.add_field("flute_count", "Flutes (optional)", integer_spin(0, 50))
        self.add_field("hole_depth_mm", "Hole depth (mm)", double_spin(20.0, step=0.1))
        self.add_field("hole_type", "Hole", combo(("Through hole", "Blind hole")))
        self.add_field("existing_hole_diameter_mm", "Existing hole (mm)", double_spin(9.8, step=0.1))
        self.add_field("material_thickness_mm", "Material thickness (mm)", double_spin(25.0, step=0.1))
        self.add_field("known_reaming_allowance_mm", "Known allowance (mm, optional)", double_spin(0.0, step=0.01))
        self.add_heading("Coolant")
        internal = QCheckBox("Internal / through-tool coolant")
        flood = QCheckBox("Flood coolant")
        flood.setChecked(True)
        self.add_field("internal_coolant", "", internal)
        self.add_field("flood_coolant", "", flood)
        self.add_hint("Reaming uses a continuous feed. The calculator will not suggest a drilling-style peck cycle.")


class TapPage(FieldPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__("Tap", parent)
        self.add_heading("Thread details")
        standard = combo(("Metric coarse", "Metric fine", "UNC", "UNF", "Custom"))
        self.add_field("thread_standard", "Thread standard", standard)
        size = combo(("M3", "M4", "M5", "M6", "M8", "M10", "M12", "M16", "M20", "M24", "Custom"), editable=True)
        self.add_field("thread_size", "Thread size", size)
        self.add_field("diameter_mm", "Nominal diameter (mm)", double_spin(10.0, maximum=100.0, step=0.1))
        pitch = double_spin(1.5, maximum=25.0, decimals=3, step=0.05)
        self.add_field("pitch_mm", "Pitch (mm)", pitch)
        self.add_field("tap_type", "Tap type", combo(("Cutting tap", "Form tap")))
        self.add_field("tool_material", "Tool material", combo(("HSS", "HSS-Co / Cobalt", "Carbide")))
        self.add_field("hole_type", "Hole", combo(("Through hole", "Blind hole")))
        self.add_field("thread_depth_mm", "Thread depth (mm)", double_spin(15.0, step=0.1))
        self.add_field("existing_hole_diameter_mm", "Existing hole (mm, optional)", double_spin(0.0, step=0.1))
        rigid = QCheckBox("Rigid tapping enabled")
        rigid.setChecked(True)
        self.add_field("rigid_tapping", "", rigid)
        self.add_field("coolant_type", "Coolant / lubricant", combo(("Flood coolant", "Tapping oil", "Mist", "Air blast", "None / dry")))
        standard.currentTextChanged.connect(self._standard_changed)
        size.currentTextChanged.connect(self._size_changed)
        self._size_changed(size.currentText())

    def _standard_changed(self, standard: str) -> None:
        if standard.startswith("Metric"):
            self._size_changed(self.fields["thread_size"].currentText())

    def _size_changed(self, size: str) -> None:
        common_pitch = {
            "M3": 0.5,
            "M4": 0.7,
            "M5": 0.8,
            "M6": 1.0,
            "M8": 1.25,
            "M10": 1.5,
            "M12": 1.75,
            "M16": 2.0,
            "M20": 2.5,
            "M24": 3.0,
        }
        value = common_pitch.get(size.strip().upper())
        if value is not None:
            self.fields["pitch_mm"].setValue(value)  # type: ignore[union-attr]
        try:
            if size.strip().upper().startswith("M"):
                nominal = float(size.strip()[1:])
                self.fields["diameter_mm"].setValue(nominal)  # type: ignore[union-attr]
        except ValueError:
            pass


class EndMillPage(FieldPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__("End Mill", parent)
        self.add_heading("Cutter details")
        self.add_field("diameter_mm", "Diameter (mm)", double_spin(10.0))
        self.add_field("flute_count", "Number of flutes", integer_spin(2, 50))
        self.add_field("tool_material", "Tool material", combo(("Carbide", "HSS", "HSS-Co / Cobalt")))
        self.add_field("coating", "Coating", combo(("Uncoated", "TiN", "TiCN", "TiAlN", "AlTiN", "Other")))
        self.add_field("stickout_mm", "Tool stickout (mm)", double_spin(30.0, step=0.1))
        self.add_field("cutting_edge_length_mm", "Cutting edge length (mm, optional)", double_spin(0.0, step=0.1))
        self.add_field("corner_radius_mm", "Corner radius (mm, optional)", double_spin(0.0, step=0.1))
        operation = combo(("Slotting", "Profiling", "Pocketing", "Adaptive / Dynamic Milling", "Finishing", "Plunging", "Helical interpolation", "Ramp"))
        self.add_field("operation", "Operation", operation)
        self.add_field("axial_doc_mm", "Axial DOC (mm)", double_spin(3.0, step=0.1))
        self.add_field("radial_doc_mm", "Radial DOC / width (mm)", double_spin(3.0, step=0.1))
        self.add_field("stock_remaining_mm", "Stock remaining (mm, optional)", double_spin(0.0, step=0.1))
        self.add_field("pocket_depth_mm", "Pocket depth (mm, optional)", double_spin(0.0, step=0.1))
        self.add_field("material_thickness_mm", "Material thickness (mm, optional)", double_spin(0.0, step=0.1))
        self.add_field("finish_priority", "Priority", combo(("Balanced", "Surface finish", "Material removal")))
        self.add_field("ball_nose_mode", "Ball nose mode", combo(("Finishing", "Roughing")))
        self.add_field("surface_finish_priority", "Surface finish priority", combo(("Balanced", "High", "Maximum")))
        self.add_field("ball_nose_contact", "Ball nose contact", combo(("Not specified", "Point / shallow contact", "Full-radius contact", "Angled / ramp contact")))
        self.add_heading("Setup context")
        self.add_field("setup_rigidity", "Setup rigidity", combo(("Light", "Normal", "Rigid")))
        self.add_field("toolholder_type", "Toolholder", combo(("Collet", "Weldon / side lock", "Hydraulic", "Shrink fit", "Milling chuck", "Other")))
        self.add_field("coolant_type", "Coolant", combo(("Flood coolant", "Through-tool coolant", "Mist", "Air blast", "None / dry")))
        operation.currentTextChanged.connect(self._operation_changed)
        self._operation_changed(operation.currentText())

    def _operation_changed(self, operation: str) -> None:
        # Keep the form compact by hiding measurements that are not meaningful
        # for the selected path, while retaining the widgets for keyboard use.
        show_pocket = operation in {"Pocketing", "Helical interpolation"}
        show_stock = operation in {"Profiling", "Pocketing", "Adaptive / Dynamic Milling", "Finishing"}
        self.set_field_visible("pocket_depth_mm", show_pocket)
        self.set_field_visible("stock_remaining_mm", show_stock)
        self.operation_changed.emit(operation)


class IndexablePage(FieldPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__("Indexable Cutter", parent)
        self.add_heading("Cutter and insert details")
        self.add_field("cutter_diameter_mm", "Cutter diameter (mm)", double_spin(25.0))
        self.add_field("insert_count", "Number of inserts", integer_spin(2, 100))
        self.add_field("insert_shape", "Insert shape / type", combo(("Square", "Round / button", "APKT", "XDPT", "Other")))
        self.add_field("insert_code", "Insert designation (optional)", QLineEdit())
        self.add_field("insert_grade", "Insert grade (optional)", QLineEdit())
        self.add_field("cutter_type", "Cutter type", combo(("Face mill", "Shoulder mill", "High feed mill", "Round/button cutter", "General indexable cutter")))
        self.add_field("operation", "Operation", combo(("Facing", "Profiling", "Pocketing", "Roughing", "Finishing")))
        self.add_field("axial_doc_mm", "Axial DOC (mm)", double_spin(2.0, step=0.1))
        self.add_field("radial_doc_mm", "Radial engagement (mm)", double_spin(5.0, step=0.1))
        self.add_field("material_thickness_mm", "Material thickness (mm, optional)", double_spin(0.0, step=0.1))
        self.add_field("stock_remaining_mm", "Stock to remove (mm, optional)", double_spin(0.0, step=0.1))
        self.add_field("stickout_mm", "Cutter stickout (mm, optional)", double_spin(0.0, step=0.1))
        self.add_heading("Setup context")
        self.add_field("setup_rigidity", "Setup rigidity", combo(("Light", "Normal", "Rigid")))
        self.add_field("toolholder_type", "Toolholder", combo(("Collet", "Weldon / side lock", "Hydraulic", "Shrink fit", "Milling chuck", "Other")))
        self.add_field("coolant_type", "Coolant", combo(("Flood coolant", "Through-tool coolant", "Mist", "Air blast", "None / dry")))
