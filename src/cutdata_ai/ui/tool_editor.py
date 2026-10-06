"""Type-shaped editing panels for Tool Library records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..config.constants import (
    COATINGS,
    METRIC_COARSE_PITCH_MM,
    TOOL_TYPES,
    metric_thread_for_tool,
    metric_thread_from_text,
    tool_family,
    tool_materials_for,
)
from .widgets import double_spin, integer_spin


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    # text | number | count | choice | check | multiline | insert | groups
    kind: str = "text"
    maximum: float = 100000.0
    decimals: int = 3
    step: float = 0.5
    options: tuple[str, ...] = ()
    editable: bool = False
    # Stored in the record's details instead of its own column.
    detail: bool = False
    placeholder: str = ""


_SOURCE_FIELDS = (
    Field("confidence", "Record confidence", "choice", options=("unknown", "low", "medium", "high")),
    Field("source_type", "Source type", "choice", editable=True,
          options=("user_supplied", "manual", "pasted_text", "manufacturer_webpage", "web_search", "unknown")),
    Field("source_url", "Source URL"),
    Field("source_title", "Source page title"),
    Field("source_retrieved_at", "Retrieved / imported at"),
    Field("source_text", "Retained source text", "multiline"),
)

TOOL_MAIN_FIELDS = (
    Field("tool_type", "Tool type", "choice", options=TOOL_TYPES),
    Field("display_name", "Name", placeholder="Named automatically from the details below"),
    Field("manufacturer", "Manufacturer", "choice", editable=True),
    Field("thread_size", "Thread size", detail=True, placeholder="e.g. M10"),
    Field("thread_pitch_mm", "Thread pitch (mm)", "number", maximum=25.0, step=0.25, detail=True),
    Field("tap_type", "Tap type", "choice", options=("Cutting tap", "Form tap"), detail=True),
    Field("diameter_mm", "Diameter (mm)", "number", maximum=1000.0),
    Field("effective_cutting_diameter_mm", "Effective cutting diameter (mm)", "number", maximum=1000.0),
    Field("flute_count", "Flutes", "count"),
    Field("insert_count", "Number of tips", "count"),
    Field("linked_insert_id", "Insert / tip", "insert"),
    Field("tool_material", "Tool material", "choice"),
    Field("coating", "Coating", "choice", editable=True),
    Field("corner_radius_mm", "Corner radius (mm)", "number", maximum=100.0, step=0.1),
    Field("ball_radius_mm", "Ball radius (mm)", "number", maximum=500.0),
    Field("cutting_edge_length_mm", "Cutting length (mm)", "number", maximum=2000.0),
    Field("point_angle_deg", "Point angle (degrees)", "number", maximum=180.0, decimals=1, step=1.0, detail=True),
    Field("approach_angle_deg", "Approach angle (degrees)", "number", maximum=180.0, decimals=1, step=1.0),
    Field("default_stickout_mm", "Usual stickout (mm)", "number", maximum=2000.0),
    Field("notes", "Notes", "multiline"),
    Field("needs_review", "Needs review (details not yet checked)", "check"),
)
TOOL_CATALOGUE_FIELDS = (
    Field("product_family", "Product family"),
    Field("model_code", "Model / code"),
    Field("manufacturer_part_number", "Manufacturer part number"),
    Field("shank_diameter_mm", "Shank diameter (mm)", "number", maximum=1000.0),
    Field("overall_length_mm", "Overall length (mm)", "number", maximum=5000.0),
    Field("hand", "Hand", "choice", editable=True, options=("", "Right hand", "Left hand")),
    Field("holder_interface", "Holder interface"),
) + _SOURCE_FIELDS

INSERT_MAIN_FIELDS = (
    Field("display_name", "Name", placeholder="Named automatically from maker, designation and grade"),
    Field("manufacturer", "Manufacturer", "choice", editable=True),
    Field("designation", "Designation", placeholder="e.g. XDPT170408PESRMM"),
    Field("grade", "Grade", placeholder="e.g. WP25PM"),
    Field("shape", "Shape", "choice", editable=True,
          options=("", "Round", "Square", "Rhombic", "Parallelogram", "Triangle", "Octagon")),
    Field("corner_radius_mm", "Corner radius (mm)", "number", maximum=100.0, step=0.1),
    Field("inscribed_circle_mm", "Insert diameter / IC (mm)", "number", maximum=200.0),
    Field("cutting_edge_count", "Cutting edges", "count"),
    Field("coating", "Coating", "choice", editable=True),
    Field("needs_review", "Needs review (details not yet checked)", "check"),
)
INSERT_CATALOGUE_FIELDS = (
    Field("product_family", "Product family"),
    Field("iso_designation", "ISO designation"),
    Field("ansi_designation", "ANSI designation"),
    Field("manufacturer_part_number", "Manufacturer part number"),
    Field("geometry", "Geometry"),
    Field("chipbreaker", "Chipbreaker"),
    Field("insert_size", "Insert size"),
    Field("thickness_mm", "Thickness (mm)", "number", maximum=100.0, step=0.1),
    Field("substrate", "Substrate"),
    Field("iso_material_groups", "ISO material groups (comma separated)", "groups"),
    Field("manufacturer_application", "Manufacturer application", "multiline"),
    Field("manufacturer_notes", "Catalogue / insert notes", "multiline"),
) + _SOURCE_FIELDS

_ALWAYS = ("tool_type", "display_name", "manufacturer", "notes", "needs_review")
_SOLID_MILL = ("diameter_mm", "flute_count", "tool_material", "coating", "corner_radius_mm",
               "cutting_edge_length_mm", "default_stickout_mm")
_ANGLED = ("diameter_mm", "flute_count", "tool_material", "coating", "point_angle_deg")
TOOL_TYPE_FIELDS: dict[str, tuple[str, ...]] = {
    "Drill": ("diameter_mm", "tool_material", "coating", "cutting_edge_length_mm", "point_angle_deg", "default_stickout_mm"),
    "Spot Drill / Centre Drill": ("diameter_mm", "tool_material", "coating", "point_angle_deg"),
    "Countersink": _ANGLED,
    "Chamfer Mill": _ANGLED,
    "Chamfer Tool": _ANGLED,
    "Reamer": ("diameter_mm", "flute_count", "tool_material", "coating", "cutting_edge_length_mm"),
    "Tap": ("thread_size", "thread_pitch_mm", "tap_type", "tool_material", "coating"),
    "Thread Mill": ("thread_size", "thread_pitch_mm", "diameter_mm", "flute_count", "tool_material", "coating", "cutting_edge_length_mm"),
    "End Mill": _SOLID_MILL,
    "Bull Nose / Corner Radius End Mill": _SOLID_MILL,
    "Ball Nose End Mill": ("diameter_mm", "flute_count", "tool_material", "coating", "ball_radius_mm",
                           "cutting_edge_length_mm", "default_stickout_mm"),
    "Face Mill": ("diameter_mm", "insert_count", "linked_insert_id", "approach_angle_deg", "default_stickout_mm"),
    "Indexable End Mill": ("diameter_mm", "insert_count", "linked_insert_id", "default_stickout_mm"),
    "Round Insert / Bull Cutter": ("diameter_mm", "effective_cutting_diameter_mm", "insert_count",
                                   "linked_insert_id", "default_stickout_mm"),
}
# Starting values offered for a new tool of each type.
TOOL_TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "Drill": {"tool_material": "HSS", "point_angle_deg": 118.0},
    "Spot Drill / Centre Drill": {"tool_material": "HSS", "point_angle_deg": 90.0},
    "Countersink": {"tool_material": "HSS", "point_angle_deg": 90.0},
    "Chamfer Mill": {"tool_material": "Carbide", "point_angle_deg": 90.0},
    "Reamer": {"tool_material": "HSS"},
    "Tap": {"tool_material": "HSS", "tap_type": "Cutting tap"},
    "Thread Mill": {"tool_material": "Carbide"},
    "End Mill": {"tool_material": "Carbide", "flute_count": 4},
    "Ball Nose End Mill": {"tool_material": "Carbide", "flute_count": 2},
    "Bull Nose / Corner Radius End Mill": {"tool_material": "Carbide", "flute_count": 4},
}
_LABEL_OVERRIDES = {
    ("Drill", "cutting_edge_length_mm"): "Flute length (mm)",
    ("Countersink", "point_angle_deg"): "Included angle (degrees)",
    ("Chamfer Mill", "point_angle_deg"): "Included angle (degrees)",
    ("Chamfer Tool", "point_angle_deg"): "Included angle (degrees)",
    ("Thread Mill", "thread_size", ): "Thread size (optional)",
    ("Thread Mill", "diameter_mm"): "Cutter diameter (mm)",
}
_SHORT_TYPE = {
    "Bull Nose / Corner Radius End Mill": "Bull Nose End Mill",
    "Round Insert / Bull Cutter": "Round Insert Cutter",
    "Spot Drill / Centre Drill": "Spot Drill",
}
_SHORT_MATERIAL = {"HSS-Co / Cobalt": "HSS-Co"}


def short_tool_type(tool_type: str) -> str:
    return _SHORT_TYPE.get(tool_type, tool_type)


def tool_type_fields(tool_type: str) -> tuple[str, ...]:
    return TOOL_TYPE_FIELDS.get(tool_type, _SOLID_MILL)


def _positive(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def default_tool_name(values: dict[str, Any]) -> str:
    """A recognisable workshop name built from the entered facts."""

    tool_type = str(values.get("tool_type") or "Tool").strip()
    label = short_tool_type(tool_type)
    shown = tool_type_fields(tool_type)
    material = str(values.get("tool_material") or "").strip()
    material = "" if "tool_material" not in shown else _SHORT_MATERIAL.get(material, material)
    diameter = _positive(values.get("diameter_mm"))
    size = f"{diameter:g}mm" if diameter else ""
    count = ""
    if tool_type in {"Tap", "Thread Mill"}:
        thread = str(values.get("thread_size") or "").strip()
        parsed = metric_thread_from_text(thread)
        pitch = _positive(values.get("thread_pitch_mm"))
        if parsed:
            size = parsed[0] + (f" x {pitch:g}" if pitch else "")
        elif thread:
            size = thread
        if tool_type == "Tap" and str(values.get("tap_type") or "").casefold().startswith("form"):
            label = "Form Tap"
    elif "insert_count" in shown:
        tips = int(_positive(values.get("insert_count")))
        count = f"{tips}-Tip" if tips else ""
    elif "flute_count" in shown:
        flutes = int(_positive(values.get("flute_count")))
        count = f"{flutes}-Flute" if flutes else ""
    return " ".join(part for part in (size, count, material, label) if part)


def default_insert_name(values: dict[str, Any]) -> str:
    parts = (str(values.get(key) or "").strip() for key in ("manufacturer", "designation", "grade"))
    return " ".join(part for part in parts if part) or "Insert / tip"


def parse_size_list(text: str, tool_type: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Read '5, 6.8, 8.5' or 'M6 M8 M10x1.25' as sizes; returns (sizes, not understood)."""

    threaded = tool_type == "Tap"
    text = re.sub(r"\s*[xX×*]\s*", "x", str(text or ""))
    tokens = [token.strip() for token in re.split(r"[,;\n]+" if re.search(r"[,;\n]", text) else r"\s+", text)]
    sizes: list[dict[str, Any]] = []
    rejected: list[str] = []
    seen: set[tuple[float, float]] = set()
    for token in (item for item in tokens if item):
        size: dict[str, Any] | None = None
        if threaded:
            parsed = metric_thread_from_text(token if token[:1].casefold() == "m" else "M" + token)
            if parsed:
                nominal = float(parsed[0][1:])
                pitch = parsed[1] or METRIC_COARSE_PITCH_MM.get(nominal)
                size = {"diameter_mm": nominal, "thread_size": parsed[0], "thread_pitch_mm": pitch}
        else:
            cleaned = re.sub(r"(?i)mm|ø", "", token).strip()
            try:
                diameter = float(cleaned)
            except ValueError:
                diameter = 0.0
            if 0.0 < diameter <= 1000.0:
                size = {"diameter_mm": diameter}
        if size is None:
            rejected.append(token)
            continue
        key = (size["diameter_mm"], size.get("thread_pitch_mm") or 0.0)
        if key not in seen:
            seen.add(key)
            sizes.append(size)
    return sizes, rejected


class RecordPanel(QWidget):
    """A form over one library record: essentials on top, catalogue details collapsed."""

    committed = Signal()
    MAIN: tuple[Field, ...] = ()
    CATALOGUE: tuple[Field, ...] = ()

    def __init__(self, library=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.library = library
        self.record: dict[str, Any] = {}
        self.is_new = True
        self.dirty = False
        self._loading = False
        self._name_auto = True
        self.widgets: dict[str, QWidget] = {}
        self._rows: dict[str, QWidget] = {}
        self._labels: dict[str, QLabel] = {}
        self._fields = {field.key: field for field in self.MAIN + self.CATALOGUE}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.main_form = QFormLayout()
        self.main_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(self.main_form)
        for field in self.MAIN:
            self._add(self.main_form, field)
        self.catalogue_toggle = QPushButton()
        self.catalogue_toggle.setObjectName("sectionToggle")
        self.catalogue_toggle.setCheckable(True)
        self.catalogue_box = QWidget()
        self.catalogue_form = QFormLayout(self.catalogue_box)
        self.catalogue_form.setContentsMargins(0, 4, 0, 0)
        self.catalogue_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for field in self.CATALOGUE:
            self._add(self.catalogue_form, field)
        self.catalogue_toggle.toggled.connect(self._catalogue_toggled)
        self._catalogue_toggled(False)
        layout.addWidget(self.catalogue_toggle)
        layout.addWidget(self.catalogue_box)
        layout.addStretch(1)
        name = self.widgets["display_name"]
        name.textEdited.connect(self._name_edited)  # type: ignore[union-attr]

    # Construction ---------------------------------------------------------
    def _add(self, form: QFormLayout, field: Field) -> None:
        widget, row = self._make(field)
        widget.setObjectName("libraryField_" + field.key)
        self.widgets[field.key] = widget
        self._rows[field.key] = row
        if field.kind == "check":
            form.addRow(row)
        else:
            label = QLabel(field.label)
            self._labels[field.key] = label
            form.addRow(label, row)

    def _make(self, field: Field) -> tuple[QWidget, QWidget]:
        if field.kind == "number":
            widget: QWidget = double_spin(maximum=field.maximum, decimals=field.decimals, step=field.step)
            widget.valueChanged.connect(lambda _value, key=field.key: self._changed(key))
            widget.editingFinished.connect(self._commit)
        elif field.kind == "count":
            widget = integer_spin(maximum=200)
            widget.valueChanged.connect(lambda _value, key=field.key: self._changed(key))
            widget.editingFinished.connect(self._commit)
        elif field.kind in {"choice", "insert"}:
            widget = QComboBox()
            widget.addItems(list(field.options))
            widget.setEditable(field.editable)
            widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            if field.editable:
                widget.setInsertPolicy(QComboBox.NoInsert)
                widget.lineEdit().editingFinished.connect(self._commit)
            widget.currentTextChanged.connect(lambda _text, key=field.key: self._changed(key))
            widget.activated.connect(lambda _index: self._commit())
        elif field.kind == "check":
            widget = QCheckBox(field.label)
            widget.toggled.connect(lambda _checked, key=field.key: self._changed(key))
            widget.clicked.connect(lambda _checked: self._commit())
        elif field.kind == "multiline":
            widget = QPlainTextEdit()
            widget.setMaximumHeight(72)
            widget.textChanged.connect(lambda key=field.key: self._changed(key))
            widget.installEventFilter(self)
        else:
            widget = QLineEdit()
            widget.setPlaceholderText(field.placeholder)
            widget.textChanged.connect(lambda _text, key=field.key: self._changed(key))
            widget.editingFinished.connect(self._commit)
        return widget, widget

    def eventFilter(self, watched, event):  # noqa: N802 - Qt naming
        if event.type() == QEvent.FocusOut and isinstance(watched, QPlainTextEdit):
            self._commit()
        return super().eventFilter(watched, event)

    def _catalogue_toggled(self, visible: bool) -> None:
        self.catalogue_box.setVisible(visible)
        self.catalogue_toggle.setText(("▾" if visible else "▸") + "  Catalogue details (part numbers, source)")

    # Values ---------------------------------------------------------------
    def get(self, key: str) -> Any:
        field, widget = self._fields[key], self.widgets[key]
        if isinstance(widget, QDoubleSpinBox):
            return widget.value() or None
        if isinstance(widget, QSpinBox):
            return widget.value() or None
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText().strip()
        if isinstance(widget, QComboBox):
            if field.kind == "insert":
                return widget.currentData()
            text = widget.currentText().strip()
            return "" if text == "Unknown" else text
        text = widget.text().strip()  # type: ignore[union-attr]
        if field.kind == "groups":
            return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
        return text

    def set(self, key: str, value: Any) -> None:
        field, widget = self._fields[key], self.widgets[key]
        if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
            number = _positive(value)
            widget.setValue(int(number) if isinstance(widget, QSpinBox) else number)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QPlainTextEdit):
            widget.setPlainText(str(value or ""))
        elif isinstance(widget, QComboBox):
            if field.kind == "insert":
                index = widget.findData(value)
                widget.setCurrentIndex(index if index >= 0 else 0)
                return
            text = str(value or "").strip()
            if not text and widget.findText("Unknown") >= 0:
                text = "Unknown"
            index = next((i for i in range(widget.count()) if widget.itemText(i).casefold() == text.casefold()), -1)
            if index < 0:
                # Keep a recorded value the standard list does not have.
                widget.addItem(text)
                index = widget.count() - 1
            widget.setCurrentIndex(index)
        elif field.kind == "groups" and isinstance(value, (list, tuple)):
            widget.setText(", ".join(str(item) for item in value))  # type: ignore[union-attr]
        else:
            widget.setText("" if value is None else str(value))  # type: ignore[union-attr]

    def _stored(self, record: dict[str, Any], field: Field) -> Any:
        if field.detail:
            return (record.get("details") or {}).get(field.key)
        return record.get(field.key)

    def visible_keys(self) -> set[str]:
        return {field.key for field in self.MAIN}

    def flat_values(self) -> dict[str, Any]:
        return {key: self.get(key) for key in self._fields}

    def default_name(self) -> str:
        return ""

    def values(self) -> dict[str, Any]:
        visible = self.visible_keys()
        out: dict[str, Any] = {}
        details = dict(self.record.get("details") or {})
        for field in self.MAIN + self.CATALOGUE:
            shown = field in self.CATALOGUE or field.key in visible
            if field.detail:
                value = self.get(field.key) if shown else None
                if value in (None, ""):
                    details.pop(field.key, None)
                else:
                    details[field.key] = value
            elif shown:
                out[field.key] = self.get(field.key)
        out["details"] = details
        if self._name_auto or not out.get("display_name"):
            out["display_name"] = self.default_name()
        return out

    # Loading --------------------------------------------------------------
    def _fill_options(self) -> None:
        makers = self.library.list_manufacturers() if self.library is not None else []
        combo = self.widgets["manufacturer"]
        combo.clear()  # type: ignore[union-attr]
        combo.addItems([""] + makers)  # type: ignore[union-attr]
        if "coating" in self.widgets:
            coating = self.widgets["coating"]
            coating.clear()  # type: ignore[union-attr]
            coating.addItems(["Unknown", *COATINGS])  # type: ignore[union-attr]

    def load(self, record: dict[str, Any] | None, initial: dict[str, Any] | None = None) -> None:
        self._loading = True
        try:
            self.record = dict(record or {})
            self.is_new = "id" not in self.record
            self._fill_options()
            source = dict(self.record)
            if self.is_new:
                source.setdefault("source_type", "user_supplied")
                source.setdefault("confidence", "unknown")
                source.setdefault("needs_review", False)
            self._load_fields(source, dict(initial or {}))
            name = str(self.get("display_name") or "")
            self._name_auto = not name or name == self.default_name()
            self._refresh_name()
        finally:
            self._loading = False
        self.dirty = False

    def _load_fields(self, source: dict[str, Any], initial: dict[str, Any]) -> None:
        for field in self.MAIN + self.CATALOGUE:
            value = initial[field.key] if field.key in initial else self._stored(source, field)
            self.set(field.key, value)

    def set_record(self, record: dict[str, Any]) -> None:
        """Adopt the saved record without touching what is on screen."""

        self.record = dict(record)
        self.is_new = "id" not in self.record
        self.dirty = False

    # Change handling ------------------------------------------------------
    def _name_edited(self, text: str) -> None:
        self._name_auto = not text.strip()

    def _refresh_name(self) -> None:
        if self._name_auto:
            widget = self.widgets["display_name"]
            widget.blockSignals(True)
            widget.setText(self.default_name())  # type: ignore[union-attr]
            widget.blockSignals(False)

    def _changed(self, key: str) -> None:
        if self._loading:
            return
        self.dirty = True
        self._loading = True
        try:
            self._dependents(key)
        finally:
            self._loading = False
        if key != "display_name":
            self._refresh_name()

    def _dependents(self, key: str) -> None:
        return

    def _commit(self) -> None:
        if not self._loading and self.dirty:
            self.committed.emit()


class ToolPanel(RecordPanel):
    MAIN = TOOL_MAIN_FIELDS
    CATALOGUE = TOOL_CATALOGUE_FIELDS

    def __init__(self, library=None, inserts: list[dict[str, Any]] | None = None, parent: QWidget | None = None):
        super().__init__(library, parent)
        self._inserts = list(inserts or [])
        self._applied_defaults: dict[str, Any] = {}
        self._auto_ball_radius = 0.0
        self.new_insert_button.clicked.connect(self._new_insert)
        self.new_insert_button.setVisible(library is not None)

    def _make(self, field: Field) -> tuple[QWidget, QWidget]:
        widget, row = super()._make(field)
        if field.kind == "insert":
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(widget, 1)
            self.new_insert_button = QPushButton("New insert…")
            layout.addWidget(self.new_insert_button)
        return widget, row

    def tool_type(self) -> str:
        return self.widgets["tool_type"].currentText().strip()  # type: ignore[union-attr]

    def visible_keys(self) -> set[str]:
        return set(_ALWAYS) | set(tool_type_fields(self.tool_type()))

    def default_name(self) -> str:
        return default_tool_name(self.flat_values())

    def _fill_inserts(self) -> None:
        if self.library is not None:
            self._inserts = self.library.list_inserts()
        combo = self.widgets["linked_insert_id"]
        combo.blockSignals(True)
        selected = combo.currentData()  # type: ignore[union-attr]
        combo.clear()  # type: ignore[union-attr]
        combo.addItem("No linked insert", None)  # type: ignore[union-attr]
        for insert in self._inserts:
            detail = " / ".join(str(part) for part in (insert.get("designation"), insert.get("grade")) if part)
            name = str(insert.get("display_name") or "Insert / tip")
            combo.addItem(name + (f" · {detail}" if detail and detail not in name else ""), int(insert["id"]))  # type: ignore[union-attr]
        index = combo.findData(selected)  # type: ignore[union-attr]
        combo.setCurrentIndex(index if index >= 0 else 0)  # type: ignore[union-attr]
        combo.blockSignals(False)

    def refresh_inserts(self) -> None:
        was_loading, self._loading = self._loading, True
        self._fill_inserts()
        self._loading = was_loading

    def _fill_options(self) -> None:
        super()._fill_options()
        self._fill_inserts()

    def _fill_materials(self) -> None:
        combo = self.widgets["tool_material"]
        current = combo.currentText()  # type: ignore[union-attr]
        combo.blockSignals(True)
        combo.clear()  # type: ignore[union-attr]
        combo.addItems(["Unknown", *tool_materials_for(self.tool_type())])  # type: ignore[union-attr]
        combo.blockSignals(False)
        self.set("tool_material", current)

    def _load_fields(self, source: dict[str, Any], initial: dict[str, Any]) -> None:
        self._applied_defaults = {}
        source = {**source, "tool_type": initial.get("tool_type") or source.get("tool_type") or "End Mill"}
        initial = {key: value for key, value in initial.items() if key != "tool_type"}
        self.set("tool_type", source["tool_type"])
        self._fill_materials()
        if self.tool_type() in {"Tap", "Thread Mill"} and not (source.get("details") or {}).get("thread_size"):
            # Older records carry the thread only in the name or diameter.
            size, pitch = metric_thread_for_tool({**source, **initial})
            details = dict(source.get("details") or {})
            if size and self.tool_type() == "Tap":
                details.setdefault("thread_size", size)
                if pitch:
                    details.setdefault("thread_pitch_mm", pitch)
            source = {**source, "details": details}
        super()._load_fields(source, initial)
        if self.is_new:
            self._apply_defaults(skip=set(initial))
        self._auto_ball_radius = 0.0
        self._apply_type()

    def _apply_defaults(self, skip: set[str] = frozenset()) -> None:
        defaults = TOOL_TYPE_DEFAULTS.get(self.tool_type(), {})
        for key, previous in list(self._applied_defaults.items()):
            if key not in defaults and self.get(key) == previous:
                self.set(key, None)
        applied: dict[str, Any] = {}
        for key, value in defaults.items():
            if key in skip:
                continue
            current = self.get(key)
            if current in (None, "") or current == self._applied_defaults.get(key):
                self.set(key, value)
                applied[key] = value
        self._applied_defaults = applied

    def _apply_type(self) -> None:
        tool_type = self.tool_type()
        visible = self.visible_keys()
        for field in self.MAIN:
            self.main_form.setRowVisible(self._rows[field.key], field.key in visible)
            if field.key in self._labels:
                self._labels[field.key].setText(_LABEL_OVERRIDES.get((tool_type, field.key), field.label))

    def _dependents(self, key: str) -> None:
        if key == "tool_type":
            self._fill_materials()
            if self.is_new:
                self._apply_defaults()
            self._apply_type()
        elif key == "thread_size":
            parsed = metric_thread_from_text(self.get("thread_size"))
            if parsed:
                pitch = parsed[1] or METRIC_COARSE_PITCH_MM.get(float(parsed[0][1:]))
                if pitch:
                    self.set("thread_pitch_mm", pitch)
        elif key == "diameter_mm" and self.tool_type() == "Ball Nose End Mill":
            radius = self.get("ball_radius_mm") or 0.0
            if not radius or radius == self._auto_ball_radius:
                self._auto_ball_radius = (self.get("diameter_mm") or 0.0) / 2.0
                self.set("ball_radius_mm", self._auto_ball_radius)

    def values(self) -> dict[str, Any]:
        out = super().values()
        if self.tool_type() == "Tap":
            parsed = metric_thread_from_text(self.get("thread_size"))
            if parsed:
                out["diameter_mm"] = float(parsed[0][1:])
            elif self.is_new:
                out["diameter_mm"] = None
        return out

    def _new_insert(self) -> None:
        from .tool_library_dialog import AddInsertDialog

        dialog = AddInsertDialog(self.library, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.select_new_insert(dialog.values())

    def select_new_insert(self, values: dict[str, Any]) -> dict[str, Any]:
        """Save a new insert and link it to this cutter."""

        saved = self.library.add_insert(values)
        self.refresh_inserts()
        self.set("linked_insert_id", saved["id"])
        self.dirty = True
        self._commit()
        return saved


class InsertPanel(RecordPanel):
    MAIN = INSERT_MAIN_FIELDS
    CATALOGUE = INSERT_CATALOGUE_FIELDS

    def default_name(self) -> str:
        return default_insert_name(self.flat_values())
