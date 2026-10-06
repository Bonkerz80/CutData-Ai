"""Workshop-friendly Tool Library: a list beside a type-shaped editor."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QPlainTextEdit, QScrollArea,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..config.constants import COATINGS, DEFAULT_MODEL, TOOL_TYPES, model_display_name, tool_materials_for
from ..services.tool_library import INSERT_FIELDS, TOOL_FIELDS, ToolLibraryService
from .tool_editor import (
    InsertPanel, ToolPanel, default_tool_name, parse_size_list, short_tool_type, tool_type_fields,
    TOOL_TYPE_DEFAULTS,
)
from .tool_import_dialog import ToolImportDialog
from .widgets import double_spin, integer_spin


def _scrolled(panel: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(2, 2, 8, 2)
    layout.addWidget(panel)
    scroll.setWidget(holder)
    return scroll


class _RecordDialog(QDialog):
    """A new record entered on the same panel the library uses for editing."""

    def __init__(self, title: str, panel, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 600)
        self.panel = panel
        root = QVBoxLayout(self)
        root.addWidget(_scrolled(panel), 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict[str, Any]:
        return self.panel.values()


class AddToolDialog(_RecordDialog):
    """Add one tool: pick the type and only that type's boxes are asked for."""

    def __init__(self, inserts: list[dict[str, Any]] | None = None, parent=None,
                 initial: dict[str, Any] | None = None, library: ToolLibraryService | None = None):
        panel = ToolPanel(library, inserts)
        super().__init__("Add tool", panel, parent)
        panel.load(None, initial)
        self.tool_type = panel.widgets["tool_type"]


# Name used by earlier releases.
AddToolWizard = AddToolDialog


class AddInsertDialog(_RecordDialog):
    def __init__(self, library: ToolLibraryService | None = None, parent=None, initial: dict[str, Any] | None = None):
        panel = InsertPanel(library)
        super().__init__("Add insert / tip", panel, parent)
        panel.load(None, initial)


class AddSetDialog(QDialog):
    """Add several sizes of the same tool in one go."""

    TYPES = tuple(item for item in TOOL_TYPES if tool_materials_for(item) and item != "Thread Mill")

    def __init__(self, library: ToolLibraryService | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add a set of tools")
        self.resize(520, 360)
        root = QVBoxLayout(self)
        hint = QLabel("Enter the details once and list the sizes. One tool is added for each size.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        root.addWidget(hint)
        form = QFormLayout()
        self.form = form
        self.tool_type = QComboBox()
        self.tool_type.addItems(list(self.TYPES))
        form.addRow("Tool type", self.tool_type)
        self.sizes = QLineEdit()
        form.addRow("Sizes", self.sizes)
        self.material = QComboBox()
        form.addRow("Tool material", self.material)
        self.coating = QComboBox()
        self.coating.addItems(["Unknown", *COATINGS])
        self.coating.setEditable(True)
        form.addRow("Coating", self.coating)
        self.flutes = integer_spin(maximum=200)
        form.addRow("Flutes", self.flutes)
        self.manufacturer = QComboBox()
        self.manufacturer.setEditable(True)
        self.manufacturer.addItems([""] + (library.list_manufacturers() if library is not None else []))
        form.addRow("Manufacturer", self.manufacturer)
        root.addLayout(form)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)
        root.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.tool_type.currentTextChanged.connect(self._type_changed)
        for signal in (self.sizes.textChanged, self.material.currentTextChanged, self.coating.currentTextChanged,
                       self.flutes.valueChanged, self.manufacturer.currentTextChanged):
            signal.connect(self._update_preview)
        self._type_changed(self.tool_type.currentText())

    def _type_changed(self, tool_type: str) -> None:
        defaults = TOOL_TYPE_DEFAULTS.get(tool_type, {})
        self.material.blockSignals(True)
        self.material.clear()
        self.material.addItems(["Unknown", *tool_materials_for(tool_type)])
        self.material.setCurrentText(str(defaults.get("tool_material", "Unknown")))
        self.material.blockSignals(False)
        fluted = "flute_count" in tool_type_fields(tool_type)
        self.form.setRowVisible(self.flutes, fluted)
        self.flutes.setValue(int(defaults.get("flute_count", 0)) if fluted else 0)
        self.sizes.setPlaceholderText("e.g. M6, M8, M10, M12x1.25" if tool_type == "Tap" else "e.g. 5, 6.8, 8.5, 10.2")
        self._update_preview()

    def tools(self) -> list[dict[str, Any]]:
        tool_type = self.tool_type.currentText()
        sizes, _rejected = parse_size_list(self.sizes.text(), tool_type)
        defaults = TOOL_TYPE_DEFAULTS.get(tool_type, {})
        shown = tool_type_fields(tool_type)
        material = "" if self.material.currentText() == "Unknown" else self.material.currentText()
        coating = self.coating.currentText().strip()
        records = []
        for size in sizes:
            details = {key: size[key] for key in ("thread_size", "thread_pitch_mm") if size.get(key)}
            for key in ("tap_type", "point_angle_deg"):
                if key in shown and key in defaults:
                    details[key] = defaults[key]
            record: dict[str, Any] = {
                "tool_type": tool_type, "diameter_mm": size["diameter_mm"],
                "tool_material": material, "coating": "" if coating == "Unknown" else coating,
                "manufacturer": self.manufacturer.currentText().strip(),
                "flute_count": self.flutes.value() or None if "flute_count" in shown else None,
                "details": details, "needs_review": False, "source_type": "user_supplied",
            }
            record["display_name"] = default_tool_name({**record, **details})
            records.append(record)
        return records

    def _update_preview(self, *_args) -> None:
        _sizes, rejected = parse_size_list(self.sizes.text(), self.tool_type.currentText())
        tools = self.tools()
        lines = []
        if tools:
            names = ", ".join(tool["display_name"] for tool in tools[:6]) + (" …" if len(tools) > 6 else "")
            lines.append(f"Will add {len(tools)} tool{'s' if len(tools) != 1 else ''}: {names}")
        if rejected:
            lines.append("Not understood: " + ", ".join(rejected))
        self.preview.setText("\n".join(lines) or "Nothing to add yet.")
        self.buttons.button(QDialogButtonBox.Save).setEnabled(bool(tools))


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


class _SortItem(QTableWidgetItem):
    """Sorts by a numeric key when one is set, otherwise by its text."""

    def __lt__(self, other):
        mine, theirs = self.data(Qt.UserRole + 1), other.data(Qt.UserRole + 1)
        if mine is not None and theirs is not None:
            return mine < theirs
        return self.text().casefold() < other.text().casefold()


_TOOL_FILTERS: tuple[tuple[str, frozenset[str] | None], ...] = (
    ("All tools", None),
    ("Drills", frozenset({"Drill", "Spot Drill / Centre Drill"})),
    ("Taps and thread mills", frozenset({"Tap", "Thread Mill"})),
    ("Reamers", frozenset({"Reamer"})),
    ("End mills", frozenset({"End Mill", "Ball Nose End Mill", "Bull Nose / Corner Radius End Mill"})),
    ("Chamfer tools", frozenset({"Chamfer Mill", "Chamfer Tool", "Countersink"})),
    ("Insert cutters", frozenset({"Face Mill", "Indexable End Mill", "Round Insert / Bull Cutter"})),
)
_COLUMNS = {
    "tool": ("Name", "Type", "Size", "Material", "Coating", "Review"),
    "insert": ("Name", "Designation", "Grade", "Radius", "Review"),
}


def _differs(stored: Any, entered: Any) -> bool:
    def normal(value: Any) -> Any:
        if value is None or value == "" or value == [] or value == {}:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, (list, tuple)):
            return list(value)
        return value.strip() if isinstance(value, str) else value

    return normal(stored) != normal(entered)


class ToolLibraryDialog(QDialog):
    """Tools and inserts listed on the left, the selected record edited on the right."""

    def __init__(self, library: ToolLibraryService, import_service_factory: Callable[[], Any], parent=None, *, model: str = DEFAULT_MODEL):
        super().__init__(parent)
        self.library = library
        self.import_service_factory = import_service_factory
        self.model = model
        self.setWindowTitle("CutData AI — Tool Library")
        self.resize(1180, 720)
        self._filling = False
        self._current: dict[str, int | None] = {"tool": None, "insert": None}
        root = QVBoxLayout(self)
        title = QLabel("TOOL LIBRARY")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        sub = QLabel("Select a record to edit it; changes save as you go. Inserts are kept once and linked to each cutter that uses them.")
        sub.setWordWrap(True)
        sub.setObjectName("hint")
        root.addWidget(sub)
        self.tabs = QTabWidget()
        self.searches: dict[str, QLineEdit] = {}
        self.tables: dict[str, QTableWidget] = {}
        self.panels: dict[str, Any] = {"tool": ToolPanel(library), "insert": InsertPanel(library)}
        self.status: dict[str, QLabel] = {}
        self._editors: dict[str, QWidget] = {}
        self._empty: dict[str, QLabel] = {}
        self.type_filter = QComboBox()
        for label, types in _TOOL_FILTERS:
            self.type_filter.addItem(label, types)
        self.type_filter.currentIndexChanged.connect(lambda _index: self._refresh("tool"))
        for key, tab_title in (("tool", "Tools"), ("insert", "Inserts / tips")):
            splitter = QSplitter(Qt.Horizontal)
            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 0, 0)
            search_row = QHBoxLayout()
            search = QLineEdit()
            search.setPlaceholderText("Search name, manufacturer or code…")
            search.setClearButtonEnabled(True)
            search_row.addWidget(search, 1)
            if key == "tool":
                search_row.addWidget(self.type_filter)
            table = QTableWidget(0, len(_COLUMNS[key]))
            table.setHorizontalHeaderLabels(list(_COLUMNS[key]))
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setSelectionMode(QTableWidget.SingleSelection)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setStretchLastSection(True)
            table.setSortingEnabled(True)
            table.sortByColumn(0, Qt.AscendingOrder)
            left_layout.addLayout(search_row)
            left_layout.addWidget(table, 1)
            right = QWidget()
            right_layout = QVBoxLayout(right)
            right_layout.setContentsMargins(8, 0, 0, 0)
            empty = QLabel("Select a record on the left, or use ADD to create one.")
            empty.setObjectName("hint")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignTop)
            editor = QWidget()
            editor_layout = QVBoxLayout(editor)
            editor_layout.setContentsMargins(0, 0, 0, 0)
            editor_layout.addWidget(_scrolled(self.panels[key]), 1)
            panel_actions = QHBoxLayout()
            look_up = QPushButton("LOOK UP WITH AI")
            look_up.setToolTip("Search for this record's catalogue details and review them before they are saved.")
            look_up.clicked.connect(lambda _checked=False: self._import(True))
            panel_actions.addWidget(look_up)
            if key == "tool":
                notes = QPushButton("WORKSHOP NOTES")
                notes.clicked.connect(self._notes)
                panel_actions.addWidget(notes)
            status = QLabel("")
            status.setObjectName("hint")
            panel_actions.addStretch(1)
            panel_actions.addWidget(status)
            editor_layout.addLayout(panel_actions)
            right_layout.addWidget(empty)
            right_layout.addWidget(editor, 1)
            splitter.addWidget(left)
            splitter.addWidget(right)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 2)
            self.searches[key] = search
            self.tables[key] = table
            self.status[key] = status
            self._editors[key] = editor
            self._empty[key] = empty
            search.textChanged.connect(lambda _text, kind=key: self._refresh(kind))
            table.itemSelectionChanged.connect(lambda kind=key: self._selection_changed(kind))
            self.panels[key].committed.connect(lambda kind=key: self._save_current(kind))
            self.tabs.addTab(splitter, tab_title)
        self.tabs.currentChanged.connect(lambda _index: self._flush())
        root.addWidget(self.tabs, 1)

        actions = QHBoxLayout()
        self.add_button = QPushButton("ADD")
        menu = QMenu(self.add_button)
        menu.addAction("Tool…", lambda: self._add("tool"))
        menu.addAction("Set of tools (several sizes)…", self._add_set)
        menu.addAction("Insert / tip…", lambda: self._add("insert"))
        menu.addSeparator()
        menu.addAction("Look one up with AI…", lambda: self._import(False))
        self.add_button.setMenu(menu)
        actions.addWidget(self.add_button)
        for text, callback in (("DUPLICATE", self._duplicate), ("DELETE", self._delete)):
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
        for key in ("tool", "insert"):
            self._load_panel(key, self._selected_id(key))

    # Selection and list ---------------------------------------------------
    def _kind(self) -> str:
        return "tool" if self.tabs.currentIndex() == 0 else "insert"

    def _selected_id(self, kind: str | None = None) -> int | None:
        kind = kind or self._kind()
        table = self.tables[kind]
        row = table.currentRow()
        item = table.item(row, 0) if row >= 0 else None
        return int(item.data(Qt.UserRole)) if item and item.data(Qt.UserRole) is not None else None

    def _records(self, kind: str) -> list[dict[str, Any]]:
        search = self.searches[kind].text()
        if kind == "insert":
            return self.library.list_inserts(search)
        types = self.type_filter.currentData()
        return [record for record in self.library.list_tools(search) if types is None or record.get("tool_type") in types]

    @staticmethod
    def _cells(kind: str, record: dict[str, Any]) -> list[tuple[str, float | None]]:
        review = "Needs review" if record.get("needs_review") else ""
        if kind == "insert":
            radius = record.get("corner_radius_mm")
            return [
                (str(record.get("display_name") or ""), None),
                (str(record.get("designation") or ""), None),
                (str(record.get("grade") or ""), None),
                (f"R{radius:g}" if radius is not None else "", float(radius) if radius is not None else -1.0),
                (review, None),
            ]
        diameter = record.get("diameter_mm")
        details = record.get("details") or {}
        size = f"Ø{diameter:g} mm" if diameter is not None else ""
        if record.get("tool_type") == "Tap" and details.get("thread_size"):
            pitch = details.get("thread_pitch_mm")
            size = str(details["thread_size"]) + (f" x {pitch:g}" if pitch else "")
        if record.get("insert_count"):
            size += f" · {record['insert_count']} tips"
        elif record.get("flute_count"):
            size += f" · {record['flute_count']} fl"
        return [
            (str(record.get("display_name") or ""), None),
            (short_tool_type(str(record.get("tool_type") or "")), None),
            (size, float(diameter) if diameter is not None else -1.0),
            (str(record.get("tool_material") or ""), None),
            (str(record.get("coating") or ""), None),
            (review, None),
        ]

    def _refresh(self, kind: str, select: int | None = None) -> None:
        table = self.tables[kind]
        records = self._records(kind)
        wanted = select if select is not None else self._selected_id(kind)
        self._filling = True
        try:
            table.setSortingEnabled(False)
            table.setRowCount(len(records))
            for row, record in enumerate(records):
                for col, (text, sort_key) in enumerate(self._cells(kind, record)):
                    cell = _SortItem(text)
                    cell.setToolTip(text)
                    if col == 0:
                        cell.setData(Qt.UserRole, int(record["id"]))
                    if sort_key is not None:
                        cell.setData(Qt.UserRole + 1, sort_key)
                    table.setItem(row, col, cell)
            table.setSortingEnabled(True)
            table.resizeColumnsToContents()
            table.setColumnWidth(0, min(max(200, table.columnWidth(0)), 320))
            table.clearSelection()
            table.setCurrentCell(-1, -1)
            for row in range(table.rowCount()):
                if wanted is not None and table.item(row, 0).data(Qt.UserRole) == wanted:
                    table.selectRow(row)
                    break
        finally:
            self._filling = False
        if self._selected_id(kind) != self._current[kind]:
            self._load_panel(kind, self._selected_id(kind))

    def _selection_changed(self, kind: str) -> None:
        target = self._selected_id(kind)
        if self._filling or target == self._current[kind]:
            return
        self._save_current(kind, then_select=target)
        if self._current[kind] != target:
            self._load_panel(kind, target)

    def _record(self, kind: str, record_id: int | None) -> dict[str, Any] | None:
        if record_id is None:
            return None
        return self.library.get_tool(record_id) if kind == "tool" else self.library.get_insert(record_id)

    def _load_panel(self, kind: str, record_id: int | None) -> None:
        record = self._record(kind, record_id)
        self._current[kind] = int(record["id"]) if record else None
        self._editors[kind].setVisible(record is not None)
        self._empty[kind].setVisible(record is None)
        self.status[kind].setText("")
        if record:
            self.panels[kind].load(record)

    # Saving ---------------------------------------------------------------
    def _save_current(self, kind: str, then_select: int | None = None) -> None:
        """Write the panel's changes to the selected record, if there are any."""

        panel = self.panels[kind]
        record = self._record(kind, self._current[kind])
        if record is None or not panel.dirty:
            return
        changed = {key: value for key, value in panel.values().items() if _differs(record.get(key), value)}
        if not changed:
            panel.dirty = False
            return
        try:
            saved = self.library.update_tool(record["id"], changed) if kind == "tool" else self.library.update_insert(record["id"], changed)
        except Exception as exc:
            self.status[kind].setText(f"Not saved: {exc}")
            return
        panel.set_record(saved)
        self.status[kind].setText("Saved")
        self._refresh(kind, select=then_select if then_select is not None else int(saved["id"]))
        if kind == "insert":
            self.panels["tool"].refresh_inserts()

    def _flush(self) -> None:
        for kind in ("tool", "insert"):
            self._save_current(kind)

    def done(self, result: int) -> None:
        self._flush()
        super().done(result)

    # Actions --------------------------------------------------------------
    def _show(self, kind: str, record_id: int) -> None:
        """Select a record, clearing any filter that would hide it."""

        self.tabs.setCurrentIndex(0 if kind == "tool" else 1)
        self._refresh(kind, select=record_id)
        if self._selected_id(kind) != record_id:
            self.searches[kind].clear()
            if kind == "tool":
                self.type_filter.setCurrentIndex(0)
            self._refresh(kind, select=record_id)
        if kind == "insert":
            self.panels["tool"].refresh_inserts()

    def _create(self, kind: str, values: dict[str, Any]) -> dict[str, Any] | None:
        try:
            saved = self.library.add_tool(values) if kind == "tool" else self.library.add_insert(values)
        except Exception as exc:
            QMessageBox.warning(self, "Tool Library", str(exc))
            return None
        self._show(kind, int(saved["id"]))
        return saved

    def _add(self, kind: str, initial: dict[str, Any] | None = None) -> None:
        self._flush()
        if kind == "tool":
            dialog: QDialog = AddToolDialog(self.library.list_inserts(), self, initial, self.library)
        else:
            dialog = AddInsertDialog(self.library, self, initial)
        if dialog.exec() == QDialog.Accepted:
            self._create(kind, dialog.values())  # type: ignore[attr-defined]

    def _add_set(self) -> None:
        self._flush()
        dialog = AddSetDialog(self.library, self)
        if dialog.exec() == QDialog.Accepted:
            self._create_set(dialog.tools())

    def _create_set(self, tools: list[dict[str, Any]]) -> None:
        saved = None
        for values in tools:
            try:
                saved = self.library.add_tool(values)
            except Exception as exc:
                QMessageBox.warning(self, "Tool Library", str(exc))
                break
        if saved:
            self._show("tool", int(saved["id"]))

    def _duplicate(self) -> None:
        kind = self._kind()
        self._flush()
        record_id = self._current[kind]
        if record_id is None:
            return
        try:
            copy = self.library.duplicate_tool(record_id) if kind == "tool" else self.library.duplicate_insert(record_id)
        except Exception as exc:
            QMessageBox.warning(self, "Tool Library", str(exc))
            return
        self._show(kind, int(copy["id"]))

    def _delete(self) -> None:
        kind = self._kind()
        record = self._record(kind, self._current[kind])
        if record is None:
            return
        message = f"Delete {record.get('display_name', 'this record')}?"
        if kind == "insert":
            message += " Any linked cutters will be kept, unlinked, and marked Needs Review."
        if QMessageBox.question(self, "Delete library record", message) != QMessageBox.Yes:
            return
        self._remove(kind, int(record["id"]))

    def _remove(self, kind: str, record_id: int) -> None:
        self.panels[kind].dirty = False
        if kind == "tool":
            self.library.delete_tool(record_id)
        else:
            self.library.delete_insert(record_id)
            self.panels["tool"].refresh_inserts()
            self._reload("tool")
        self._current[kind] = None
        self._refresh(kind)
        self._load_panel(kind, self._selected_id(kind))

    def _reload(self, kind: str) -> None:
        """Re-read the selected record after something else changed it."""

        current = self._current[kind]
        self._current[kind] = None
        self._refresh(kind, select=current)
        if self._current[kind] is None:
            self._load_panel(kind, self._selected_id(kind))

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
        self._flush()
        record = self._record(kind, self._current[kind]) if enrich else None
        if enrich and record is None:
            QMessageBox.information(self, "AI look-up", "Select a tool or insert first.")
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
                # Keep facts the look-up does not know about, such as a thread size.
                values["details"] = {**(record.get("details") or {}), **values["details"]}
                if kind == "tool":
                    self.library.update_tool(record["id"], values)
                else:
                    self.library.update_insert(record["id"], values)
                self._reload(kind)
            else:
                self._create(kind, values)
        except Exception as exc:
            QMessageBox.warning(self, "AI look-up", str(exc))

    def _notes(self) -> None:
        record = self.library.get_tool(self._current["tool"]) if self._current["tool"] else None
        if not record:
            QMessageBox.information(self, "Workshop notes", "Select a tool first.")
            return
        WorkshopNotesDialog(self.library, record, self).exec()
