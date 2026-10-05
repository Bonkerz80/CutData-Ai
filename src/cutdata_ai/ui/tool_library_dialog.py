"""Workshop-friendly editor for cutter bodies, inserts and observations."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QPlainTextEdit, QScrollArea, QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..config.constants import DEFAULT_MODEL, TOOL_TYPES, model_display_name
from ..services.tool_library import INSERT_FIELDS, TOOL_FIELDS, ToolLibraryService
from .tool_import_dialog import ToolImportDialog
from .widgets import double_spin


_TOOL_EDIT_FIELDS = (
    "display_name", "manufacturer", "product_family", "model_code",
    "manufacturer_part_number", "tool_type", "diameter_mm",
    "effective_cutting_diameter_mm", "flute_count", "insert_count",
    "linked_insert_id", "tool_material", "coating", "corner_radius_mm",
    "ball_radius_mm", "shank_diameter_mm", "cutting_edge_length_mm",
    "overall_length_mm", "default_stickout_mm", "approach_angle_deg", "hand",
    "holder_interface", "notes", "source_type", "source_url", "source_title",
    "source_retrieved_at", "source_text", "confidence", "needs_review",
)
_INSERT_EDIT_FIELDS = (
    "display_name", "manufacturer", "product_family", "designation",
    "iso_designation", "ansi_designation", "manufacturer_part_number", "grade",
    "geometry", "chipbreaker", "shape", "insert_size", "inscribed_circle_mm",
    "thickness_mm", "corner_radius_mm", "cutting_edge_count", "coating", "substrate",
    "iso_material_groups", "manufacturer_application", "manufacturer_notes",
    "source_type", "source_url", "source_title", "source_retrieved_at", "source_text",
    "confidence", "needs_review",
)
_LABELS = {
    "display_name": "Workshop name", "product_family": "Product family",
    "model_code": "Model / code", "manufacturer_part_number": "Manufacturer part number",
    "tool_type": "Tool family", "diameter_mm": "Diameter (mm)",
    "effective_cutting_diameter_mm": "Effective cutting diameter (mm)",
    "flute_count": "Flutes", "insert_count": "Insert pockets / tips", "linked_insert_id": "Insert / tip",
    "tool_material": "Tool material", "coating": "Coating (as recorded)",
    "corner_radius_mm": "Corner radius (mm)", "ball_radius_mm": "Ball radius (mm)",
    "shank_diameter_mm": "Shank diameter (mm)", "cutting_edge_length_mm": "Cutting edge length (mm)",
    "overall_length_mm": "Overall length (mm)", "default_stickout_mm": "Preferred stickout (mm, optional)",
    "approach_angle_deg": "Approach angle (degrees)", "hand": "Hand", "holder_interface": "Holder interface",
    "notes": "Workshop notes", "designation": "Designation", "iso_designation": "ISO designation",
    "ansi_designation": "ANSI designation", "grade": "Grade", "geometry": "Geometry",
    "chipbreaker": "Chipbreaker", "shape": "Shape", "insert_size": "Insert size",
    "inscribed_circle_mm": "Nominal insert diameter / IC (mm)", "thickness_mm": "Thickness (mm)",
    "cutting_edge_count": "Known cutting edges", "substrate": "Substrate",
    "iso_material_groups": "ISO material groups (comma separated)",
    "manufacturer_application": "Manufacturer application", "manufacturer_notes": "Catalogue / insert notes",
    "source_type": "Source type", "source_url": "Source URL", "source_title": "Source page title",
    "source_retrieved_at": "Retrieved / imported at", "source_text": "Retained user-provided text",
    "confidence": "Record confidence", "needs_review": "Needs review",
}
_FLOAT_FIELDS = {
    "diameter_mm", "effective_cutting_diameter_mm", "corner_radius_mm", "ball_radius_mm",
    "shank_diameter_mm", "cutting_edge_length_mm", "overall_length_mm", "default_stickout_mm",
    "approach_angle_deg", "inscribed_circle_mm", "thickness_mm",
}
_INT_FIELDS = {"flute_count", "insert_count", "cutting_edge_count"}
_MULTILINE = {"notes", "manufacturer_notes", "source_text", "manufacturer_application"}
_STATUS_COLORS = {
    "user_supplied": "#dff3e6", "source_confirmed": "#dbeafe",
    "ai_inferred": "#fff1cc", "unknown": "#eceff1",
}


class RecordEditorDialog(QDialog):
    """Edit one library record without mixing the insert and body entities."""

    def __init__(self, entity_type: str, record: dict[str, Any] | None, inserts: list[dict[str, Any]], parent=None):
        super().__init__(parent)
        self.entity_type = entity_type
        self.record = dict(record or {})
        self.inputs: dict[str, QWidget] = {}
        self.setWindowTitle("Add tool" if record is None and entity_type == "tool" else "Add insert / tip" if record is None else "Edit workshop record")
        self.resize(650, 720)
        root = QVBoxLayout(self)
        intro = QLabel("Record only known facts. Leave unverified catalogue details blank and mark incomplete records for review.")
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        root.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fields = _TOOL_EDIT_FIELDS if entity_type == "tool" else _INSERT_EDIT_FIELDS
        for key in fields:
            label = _LABELS.get(key, key.replace("_", " ").title())
            if key == "needs_review":
                widget = QCheckBox("Needs review")
                widget.setChecked(bool(self.record.get(key, True)))
            elif key == "confidence":
                widget = QComboBox()
                widget.addItems(["unknown", "low", "medium", "high"])
                widget.setCurrentText(str(self.record.get(key, "unknown")))
            elif key == "source_type":
                widget = QComboBox()
                widget.addItems(["user_supplied", "manual", "pasted_text", "manufacturer_webpage", "web_search", "unknown"])
                widget.setEditable(True)
                widget.setCurrentText(str(self.record.get(key, "user_supplied")))
            elif key == "tool_type":
                widget = QComboBox()
                widget.addItems(list(dict.fromkeys((*TOOL_TYPES, "Round Insert / Bull Cutter", "Chamfer Tool", "Other / unknown"))))
                widget.setEditable(True)
                widget.setCurrentText(str(self.record.get(key, "End Mill")))
            elif key == "linked_insert_id":
                widget = QComboBox()
                widget.addItem("No linked insert", None)
                for insert in inserts:
                    suffix = " · " + " / ".join(part for part in (insert.get("designation"), insert.get("grade")) if part)
                    widget.addItem(str(insert.get("display_name", "Insert")) + suffix, int(insert["id"]))
                target = self.record.get(key)
                for index in range(widget.count()):
                    if widget.itemData(index) == target:
                        widget.setCurrentIndex(index)
                        break
            elif key in _MULTILINE:
                widget = QPlainTextEdit()
                widget.setPlainText(str(self.record.get(key) or ""))
                widget.setMaximumHeight(90)
            else:
                widget = QLineEdit()
                current = self.record.get(key)
                if key == "iso_material_groups" and isinstance(current, (list, tuple)):
                    current = ", ".join(str(item) for item in current)
                widget.setText("" if current is None else str(current))
                if key in _FLOAT_FIELDS or key in _INT_FIELDS:
                    widget.setValidator(QDoubleValidator(0.0, 100000.0, 5, widget))
            widget.setObjectName("libraryField_" + key)
            form.addRow(label, widget)
            self.inputs[key] = widget
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, widget in self.inputs.items():
            if isinstance(widget, QCheckBox):
                value: Any = widget.isChecked()
            elif isinstance(widget, QComboBox):
                value = widget.currentData() if key == "linked_insert_id" else widget.currentText().strip()
            elif isinstance(widget, QPlainTextEdit):
                value = widget.toPlainText().strip()
            else:
                value = widget.text().strip()
            if key in _FLOAT_FIELDS | _INT_FIELDS:
                value = value if value else None
            if key == "iso_material_groups":
                value = [part.strip() for part in str(value).replace(";", ",").split(",") if part.strip()]
            values[key] = value
        values["details"] = dict(self.record.get("details") or {})
        return values


class AddToolWizard(QDialog):
    """A short, type-first path for recording the facts needed to identify a tool."""

    _INDEXABLE = {"Face Mill", "Indexable End Mill", "Round Insert / Bull Cutter"}
    _FLUTED = {"Drill", "End Mill", "Ball Nose End Mill", "Bull Nose / Corner Radius End Mill",
               "Reamer", "Tap", "Thread Mill", "Countersink", "Chamfer Mill", "Spot Drill / Centre Drill"}

    def __init__(self, inserts: list[dict[str, Any]], parent=None, initial: dict[str, Any] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add tool — guided setup")
        self.resize(490, 420)
        self.initial = dict(initial or {})
        root = QVBoxLayout(self)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)

        first = QWidget()
        first_layout = QVBoxLayout(first)
        heading = QLabel("1 of 2 · What type of tool is it?")
        heading.setObjectName("sectionTitle")
        first_layout.addWidget(heading)
        self.tool_type = QComboBox()
        self.tool_type.setObjectName("wizardToolType")
        self.tool_type.addItems(TOOL_TYPES)
        self.tool_type.setCurrentText(str(self.initial.get("tool_type") or "End Mill"))
        first_layout.addWidget(self.tool_type)
        tip = QLabel("Choose the closest type. You can add more detail later with Edit or Enrich with AI.")
        tip.setWordWrap(True)
        first_layout.addWidget(tip)
        first_layout.addStretch(1)
        self.pages.addWidget(first)

        second = QWidget()
        second_layout = QVBoxLayout(second)
        self.details_heading = QLabel("2 of 2 · Tool details")
        self.details_heading.setObjectName("sectionTitle")
        second_layout.addWidget(self.details_heading)
        form = QFormLayout()
        self.form = form
        self.inputs: dict[str, QWidget] = {}
        for key, placeholder in (
            ("display_name", "A name you'll recognise"),
            ("diameter_mm", "e.g. 25"),
            ("manufacturer", "Optional"),
            ("model_code", "Optional"),
            ("flute_count", "Optional"),
            ("tool_material", "Optional"),
            ("insert_count", "Optional"),
            ("corner_radius_mm", "Optional"),
            ("ball_radius_mm", "Optional"),
        ):
            widget = QLineEdit()
            widget.setObjectName("wizardField_" + key)
            widget.setPlaceholderText(placeholder)
            widget.setText(str(self.initial.get(key) or ""))
            if key in _FLOAT_FIELDS | _INT_FIELDS:
                widget.setValidator(QDoubleValidator(0.0, 100000.0, 3, widget))
            form.addRow(_LABELS.get(key, key), widget)
            self.inputs[key] = widget
        self.linked_insert = QComboBox()
        self.linked_insert.setObjectName("wizardField_linked_insert_id")
        self.linked_insert.addItem("No linked insert yet", None)
        for insert in inserts:
            self.linked_insert.addItem(str(insert.get("display_name") or "Insert / tip"), int(insert["id"]))
        form.addRow("Insert / tip", self.linked_insert)
        self.inputs["linked_insert_id"] = self.linked_insert
        second_layout.addLayout(form)
        second_layout.addStretch(1)
        self.pages.addWidget(second)

        controls = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.next_button = QPushButton("Next")
        self.save_button = QPushButton("Save tool")
        cancel_button = QPushButton("Cancel")
        controls.addWidget(self.back_button)
        controls.addStretch(1)
        controls.addWidget(self.next_button)
        controls.addWidget(self.save_button)
        controls.addWidget(cancel_button)
        root.addLayout(controls)
        self.back_button.clicked.connect(lambda: self._show_page(0))
        self.next_button.clicked.connect(lambda: self._show_page(1))
        self.save_button.clicked.connect(self._save)
        cancel_button.clicked.connect(self.reject)
        self.tool_type.currentTextChanged.connect(self._update_fields)
        self._show_page(0)

    def _show_page(self, page: int) -> None:
        self.pages.setCurrentIndex(page)
        self.back_button.setVisible(page == 1)
        self.next_button.setVisible(page == 0)
        self.save_button.setVisible(page == 1)
        if page == 1:
            self.details_heading.setText(f"2 of 2 · {self.tool_type.currentText()} details")
            self._update_fields()

    def _update_fields(self) -> None:
        tool = self.tool_type.currentText()
        visible = {"display_name", "diameter_mm", "manufacturer", "model_code"}
        if tool in self._FLUTED:
            visible.update({"flute_count", "tool_material"})
        if tool in self._INDEXABLE:
            visible.update({"insert_count", "linked_insert_id"})
        if tool == "Ball Nose End Mill":
            visible.add("ball_radius_mm")
        if tool in {"Bull Nose / Corner Radius End Mill", "Round Insert / Bull Cutter"}:
            visible.add("corner_radius_mm")
        for key, widget in self.inputs.items():
            label = self.form.labelForField(widget)
            widget.setVisible(key in visible)
            if label is not None:
                label.setVisible(key in visible)

    def _save(self) -> None:
        if not self.inputs["display_name"].text().strip():
            QMessageBox.information(self, "Add tool", "Give this tool a workshop name first.")
            self.inputs["display_name"].setFocus()
            return
        self.accept()

    def values(self) -> dict[str, Any]:
        values: dict[str, Any] = {"tool_type": self.tool_type.currentText(), "source_type": "user_supplied", "needs_review": True}
        for key, widget in self.inputs.items():
            if widget.isHidden():
                continue
            raw = widget.currentData() if isinstance(widget, QComboBox) else widget.text().strip()
            if raw not in (None, ""):
                values[key] = raw
        return values


class WorkshopNotesDialog(QDialog):
    def __init__(self, library: ToolLibraryService, tool: dict[str, Any], parent=None):
        super().__init__(parent)
        self.library = library
        self.tool = tool
        self.setWindowTitle("Workshop notes — " + str(tool.get("display_name", "Tool")))
        self.resize(650, 420)
        layout = QVBoxLayout(self)
        hint = QLabel("Practical observations inform future advice as context only; they do not become fixed cutting rules.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        layout.addWidget(hint)
        self.items = QTableWidget(0, 3)
        self.items.setHorizontalHeaderLabels(["Type", "Observation", "Date"])
        self.items.setSelectionBehavior(QTableWidget.SelectRows)
        self.items.setEditTriggers(QTableWidget.NoEditTriggers)
        self.items.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.items, 1)
        controls = QHBoxLayout()
        add = QPushButton("Add workshop note")
        delete = QPushButton("Delete selected")
        controls.addWidget(add)
        controls.addWidget(delete)
        controls.addStretch(1)
        close = QPushButton("Close")
        controls.addWidget(close)
        layout.addLayout(controls)
        add.clicked.connect(self._add)
        delete.clicked.connect(self._delete)
        close.clicked.connect(self.accept)
        self._refresh()

    def _refresh(self) -> None:
        records = self.library.observations_for_tool(self.tool["id"])
        self.items.setRowCount(len(records))
        for row, record in enumerate(records):
            for col, key in enumerate(("category", "note", "created_at")):
                item = QTableWidgetItem(str(record.get(key, "")))
                if col == 0:
                    item.setData(Qt.UserRole, int(record["id"]))
                self.items.setItem(row, col, item)
        self.items.resizeColumnsToContents()
        self.items.setColumnWidth(1, max(240, self.items.columnWidth(1)))

    def _add(self) -> None:
        categories = ["Good result", "Too noisy", "Chatter", "Poor finish", "Tool wear", "Custom note", "Historical use"]
        category, ok = QInputDialog.getItem(self, "Workshop observation", "Type", categories, 0, True)
        if not ok:
            return
        note, ok = QInputDialog.getMultiLineText(self, "Workshop observation", "What happened?", "")
        if not ok or not note.strip():
            return
        try:
            self.library.add_observation(self.tool["id"], note, category)
        except (ValueError, Exception) as exc:
            QMessageBox.warning(self, "Workshop note", str(exc))
            return
        self._refresh()

    def _delete(self) -> None:
        row = self.items.currentRow()
        item = self.items.item(row, 0) if row >= 0 else None
        if item is None:
            return
        if QMessageBox.question(self, "Delete note", "Delete this workshop observation?") != QMessageBox.Yes:
            return
        self.library.delete_observation(int(item.data(Qt.UserRole)))
        self._refresh()


class WorkshopFeedbackDialog(QDialog):
    """Capture practical result feedback without turning it into a fixed rule."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Workshop feedback")
        self.resize(520, 470)
        root = QVBoxLayout(self)
        intro = QLabel("Record what happened. This is evidence for future context, not an automatic override of AI recommendations.")
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        root.addWidget(intro)
        form = QFormLayout()
        self.category = QComboBox()
        self.category.addItems(["Good result", "Too noisy", "Chatter", "Poor finish", "Tool wear", "Custom note"])
        form.addRow("Outcome", self.category)
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("Optional practical observation…")
        self.note.setMaximumHeight(110)
        form.addRow("Workshop note", self.note)
        self.actuals = {}
        for key, label, maximum, decimals in (
            ("actual_rpm", "Actual RPM (optional)", 100000.0, 0),
            ("actual_feed_mm_min", "Actual feed (mm/min, optional)", 100000.0, 0),
            ("actual_doc_mm", "Actual DOC (mm, optional)", 5000.0, 3),
            ("actual_engagement_mm", "Actual engagement (mm, optional)", 5000.0, 3),
        ):
            widget = double_spin(maximum=maximum, decimals=decimals, step=1.0)
            form.addRow(label, widget)
            self.actuals[key] = widget
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> tuple[str, str, dict[str, float | None]]:
        category = self.category.currentText()
        note = self.note.toPlainText().strip() or category
        actuals = {key: widget.value() or None for key, widget in self.actuals.items()}
        return category, note, actuals


class ToolLibraryDialog(QDialog):
    """Searchable, two-list library with review-first AI imports."""

    def __init__(self, library: ToolLibraryService, import_service_factory: Callable[[], Any], parent=None, *, model: str = DEFAULT_MODEL):
        super().__init__(parent)
        self.library = library
        self.import_service_factory = import_service_factory
        self.model = model
        self.setWindowTitle("CutData AI — Tool Library")
        self.resize(1040, 690)
        root = QVBoxLayout(self)
        title = QLabel("TOOL LIBRARY")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        sub = QLabel("Cutter bodies and inserts are stored separately, so shared tips are entered once and linked to each cutter.")
        sub.setWordWrap(True)
        sub.setObjectName("hint")
        root.addWidget(sub)
        self.tabs = QTabWidget()
        self.searches: dict[str, QLineEdit] = {}
        self.tables: dict[str, QTableWidget] = {}
        for key, tab_title in (("tool", "Cutter bodies / tools"), ("insert", "Inserts / tips")):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            search = QLineEdit()
            search.setPlaceholderText("Search name, manufacturer, family or code…")
            table = QTableWidget(0, 4)
            table.setHorizontalHeaderLabels(["Name", "Identity", "Size", "Status"])
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setSelectionMode(QTableWidget.SingleSelection)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.horizontalHeader().setStretchLastSection(True)
            page_layout.addWidget(search)
            page_layout.addWidget(table, 1)
            self.searches[key] = search
            self.tables[key] = table
            search.textChanged.connect(lambda _text, kind=key: self._refresh(kind))
            self.tabs.addTab(page, tab_title)
        root.addWidget(self.tabs, 1)

        actions = QHBoxLayout()
        for text, callback in (
            ("ADD TOOL", lambda: self._add("tool")),
            ("ADD INSERT / TIP", lambda: self._add("insert")),
            ("EDIT", self._edit),
            ("DUPLICATE", self._duplicate),
            ("DELETE", self._delete),
            ("ADD WITH AI", lambda: self._import(False)),
            ("ENRICH WITH AI", lambda: self._import(True)),
            ("WORKSHOP NOTES", self._notes),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        root.addLayout(actions)
        self._refresh("tool")
        self._refresh("insert")

    def _kind(self) -> str:
        return "tool" if self.tabs.currentIndex() == 0 else "insert"

    def _selected_id(self, kind: str | None = None) -> int | None:
        kind = kind or self._kind()
        table = self.tables[kind]
        row = table.currentRow()
        item = table.item(row, 0) if row >= 0 else None
        return int(item.data(Qt.UserRole)) if item and item.data(Qt.UserRole) is not None else None

    def _refresh(self, kind: str) -> None:
        table = self.tables[kind]
        search = self.searches[kind].text()
        records = self.library.list_tools(search) if kind == "tool" else self.library.list_inserts(search)
        previous = self._selected_id(kind)
        table.setRowCount(len(records))
        selected_row = -1
        for row, record in enumerate(records):
            if record.get("id") == previous:
                selected_row = row
            if kind == "tool":
                identity = " ".join(str(part) for part in (record.get("manufacturer"), record.get("product_family"), record.get("model_code"), record.get("manufacturer_part_number")) if part)
                size = (f"Ø{record['diameter_mm']:g} mm" if record.get("diameter_mm") is not None else "Size unknown")
                if record.get("insert_count"):
                    size += f" · {record['insert_count']} tips"
            else:
                identity = " ".join(str(part) for part in (record.get("manufacturer"), record.get("designation"), record.get("grade")) if part)
                size = (f"R{record['corner_radius_mm']:g} mm" if record.get("corner_radius_mm") is not None else str(record.get("shape") or "Dimensions unknown"))
            status = "NEEDS REVIEW" if record.get("needs_review") else str(record.get("confidence", "unknown")).upper()
            for col, text in enumerate((record.get("display_name", ""), identity, size, status)):
                cell = QTableWidgetItem(str(text or ""))
                if col == 0:
                    cell.setData(Qt.UserRole, int(record["id"]))
                if col == 3:
                    cell.setBackground(QColor(_STATUS_COLORS["unknown"] if record.get("needs_review") else _STATUS_COLORS["source_confirmed"] if record.get("confidence") == "high" else _STATUS_COLORS["ai_inferred"]))
                    cell.setForeground(QColor("#17212B"))
                cell.setToolTip(str(text or ""))
                table.setItem(row, col, cell)
        table.resizeColumnsToContents()
        table.setColumnWidth(0, max(220, table.columnWidth(0)))
        table.setColumnWidth(1, max(260, table.columnWidth(1)))
        if selected_row >= 0:
            table.selectRow(selected_row)

    def _record(self, kind: str, record_id: int | None) -> dict[str, Any] | None:
        if record_id is None:
            return None
        return self.library.get_tool(record_id) if kind == "tool" else self.library.get_insert(record_id)

    def _add(self, kind: str, initial: dict[str, Any] | None = None) -> None:
        dialog = AddToolWizard(self.library.list_inserts(), self, initial) if kind == "tool" else RecordEditorDialog(kind, initial, self.library.list_inserts(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            values = dialog.values()
            if kind == "tool":
                self.library.add_tool(values)
            else:
                self.library.add_insert(values)
        except Exception as exc:
            QMessageBox.warning(self, "Tool Library", str(exc))
            return
        self._refresh(kind)

    def _edit(self) -> None:
        kind = self._kind()
        record = self._record(kind, self._selected_id(kind))
        if record:
            dialog = RecordEditorDialog(kind, record, self.library.list_inserts(), self)
            if dialog.exec() == QDialog.Accepted:
                try:
                    if kind == "tool":
                        self.library.update_tool(record["id"], dialog.values())
                    else:
                        self.library.update_insert(record["id"], dialog.values())
                except Exception as exc:
                    QMessageBox.warning(self, "Tool Library", str(exc))
                    return
                self._refresh(kind)

    def _duplicate(self) -> None:
        kind = self._kind()
        record_id = self._selected_id(kind)
        if record_id is None:
            return
        try:
            if kind == "tool":
                self.library.duplicate_tool(record_id)
            else:
                self.library.duplicate_insert(record_id)
        except Exception as exc:
            QMessageBox.warning(self, "Tool Library", str(exc))
            return
        self._refresh(kind)

    def _delete(self) -> None:
        kind = self._kind()
        record_id = self._selected_id(kind)
        record = self._record(kind, record_id)
        if record is None:
            return
        message = f"Delete {record.get('display_name', 'this record')}?"
        if kind == "insert":
            message += " Any linked cutters will be kept, unlinked, and marked Needs Review."
        if QMessageBox.question(self, "Delete library record", message) != QMessageBox.Yes:
            return
        if kind == "tool":
            self.library.delete_tool(record_id)
        else:
            self.library.delete_insert(record_id)
            self._refresh("tool")
        self._refresh(kind)

    @staticmethod
    def _candidate_values(candidate, kind: str) -> dict[str, Any]:
        fields = TOOL_FIELDS if kind == "tool" else INSERT_FIELDS
        values = {key: candidate.fields.get(key) for key in fields if key in candidate.fields}
        values.update({
            "display_name": candidate.display_name,
            "field_provenance": candidate.field_provenance,
            "source_type": candidate.source_type,
            "source_url": candidate.source_urls[0]["url"] if candidate.source_urls else "",
            "source_title": candidate.source_title,
            "source_retrieved_at": candidate.source_retrieved_at,
            "source_text": candidate.source_text,
            "confidence": candidate.confidence,
            "needs_review": True,
            "details": {"source_urls": candidate.source_urls},
        })
        if kind == "tool" and not values.get("tool_type"):
            values["tool_type"] = "End Mill"
        return values

    def _import(self, enrich: bool) -> None:
        kind = self._kind()
        record = self._record(kind, self._selected_id(kind)) if enrich else None
        if enrich and record is None:
            QMessageBox.information(self, "AI enrichment", "Select a tool or insert first.")
            return
        dialog = ToolImportDialog(
            self.import_service_factory, kind,
            existing_record=record,
            known_fields=record or {},
            model_name=model_display_name(self.model),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted or dialog.candidate is None:
            return
        values = self._candidate_values(dialog.candidate, kind)
        try:
            if record:
                if kind == "tool":
                    self.library.update_tool(record["id"], values)
                else:
                    self.library.update_insert(record["id"], values)
            elif kind == "tool":
                self.library.add_tool(values)
            else:
                self.library.add_insert(values)
        except Exception as exc:
            QMessageBox.warning(self, "AI import", str(exc))
            return
        self._refresh(kind)

    def _notes(self) -> None:
        record_id = self._selected_id("tool")
        record = self.library.get_tool(record_id) if record_id else None
        if not record:
            QMessageBox.information(self, "Workshop notes", "Select a cutter body/tool first.")
            return
        WorkshopNotesDialog(self.library, record, self).exec()
