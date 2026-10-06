import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.cutdata_ai.database.database import Database
from src.cutdata_ai.services.tool_library import ToolLibraryService
from src.cutdata_ai.ui.tool_editor import (
    InsertPanel, ToolPanel, default_tool_name, parse_size_list, tool_type_fields,
)
from src.cutdata_ai.ui.tool_library_dialog import (
    AddInsertDialog, AddSetDialog, AddToolDialog, AddToolWizard, ToolLibraryDialog,
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def library(tmp_path):
    return ToolLibraryService(Database(tmp_path / "library.sqlite3"))


@pytest.fixture
def dialog(qapp, library):
    value = ToolLibraryDialog(library, lambda: None)
    value.show()
    qapp.processEvents()
    yield value
    value.close()
    value.deleteLater()
    qapp.processEvents()


def _shown(panel):
    return {field.key for field in panel.MAIN if not panel._rows[field.key].isHidden()}


def _select(dialog, kind, name):
    table = dialog.tables[kind]
    row = next(row for row in range(table.rowCount()) if table.item(row, 0).text() == name)
    table.selectRow(row)
    return dialog._current[kind]


def test_names_are_built_from_the_entered_facts():
    assert default_tool_name({"tool_type": "Drill", "diameter_mm": 20, "tool_material": "HSS-Co / Cobalt"}) == "20mm HSS-Co Drill"
    assert default_tool_name({"tool_type": "Tap", "thread_size": "M10", "thread_pitch_mm": 1.5, "tool_material": "HSS"}) == "M10 x 1.5 HSS Tap"
    assert default_tool_name({"tool_type": "Tap", "thread_size": "M8", "thread_pitch_mm": 1.25, "tap_type": "Form tap"}) == "M8 x 1.25 Form Tap"
    assert default_tool_name({"tool_type": "End Mill", "diameter_mm": 16, "flute_count": 4, "tool_material": "Carbide"}) == "16mm 4-Flute Carbide End Mill"
    assert default_tool_name({"tool_type": "Face Mill", "diameter_mm": 50, "insert_count": 4, "tool_material": "Carbide"}) == "50mm 4-Tip Face Mill"
    assert default_tool_name({"tool_type": "Drill", "diameter_mm": 8, "flute_count": 2}) == "8mm Drill"


def test_add_tool_shows_only_the_boxes_for_its_type_with_starting_values(qapp, library):
    dialog = AddToolDialog([], None, None, library)
    dialog.show()
    panel = dialog.panel
    always = {"tool_type", "display_name", "manufacturer", "notes", "needs_review"}
    assert AddToolWizard is AddToolDialog
    assert panel.tool_type() == "End Mill"
    assert _shown(panel) == always | set(tool_type_fields("End Mill"))
    assert panel.get("flute_count") == 4 and panel.get("tool_material") == "Carbide"
    assert not panel.catalogue_box.isVisible()

    dialog.tool_type.setCurrentText("Drill")
    assert _shown(panel) == always | {"diameter_mm", "tool_material", "coating", "cutting_edge_length_mm", "point_angle_deg", "default_stickout_mm"}
    assert panel._labels["cutting_edge_length_mm"].text() == "Flute length (mm)"
    assert panel.get("tool_material") == "HSS" and panel.get("point_angle_deg") == 118
    assert panel.widgets["tool_material"].findText("Indexable") >= 0
    panel.widgets["diameter_mm"].setValue(20)
    panel.widgets["tool_material"].setCurrentText("HSS-Co / Cobalt")
    values = dialog.values()
    assert values["display_name"] == "20mm HSS-Co Drill"
    assert values["details"] == {"point_angle_deg": 118.0}
    assert "flute_count" not in values and "insert_count" not in values
    assert values["needs_review"] is False

    saved = library.add_tool(values)
    assert saved["diameter_mm"] == 20 and saved["tool_material"] == "HSS-Co / Cobalt"
    assert library.tool_snapshot(saved["id"])["point_angle_deg"] == 118

    # A typed name is kept; clearing it goes back to the automatic one.
    panel.widgets["display_name"].setText("Big drill")
    panel.widgets["display_name"].textEdited.emit("Big drill")
    panel.widgets["diameter_mm"].setValue(22)
    assert dialog.values()["display_name"] == "Big drill"
    panel.widgets["display_name"].setText("")
    panel.widgets["display_name"].textEdited.emit("")
    assert dialog.values()["display_name"] == "22mm HSS-Co Drill"

    dialog.tool_type.setCurrentText("Ball Nose End Mill")
    panel.widgets["diameter_mm"].setValue(8)
    assert panel.get("ball_radius_mm") == 4 and panel.get("flute_count") == 2
    # A material the user chose is kept when it still suits the new type.
    assert panel.get("tool_material") == "HSS-Co / Cobalt"
    assert "point_angle_deg" not in dialog.values()["details"]
    dialog.close()


def test_tap_fills_pitch_and_diameter_from_the_thread_size(qapp, library):
    dialog = AddToolDialog([], None, {"tool_type": "Tap"}, library)
    panel = dialog.panel
    assert "diameter_mm" not in panel.visible_keys()
    panel.widgets["thread_size"].setText("M10")
    assert panel.get("thread_pitch_mm") == 1.5
    values = dialog.values()
    assert values["display_name"] == "M10 x 1.5 HSS Tap"
    assert values["diameter_mm"] == 10
    assert values["details"] == {"thread_size": "M10", "thread_pitch_mm": 1.5, "tap_type": "Cutting tap"}
    panel.widgets["thread_size"].setText("M10x1.25")
    assert panel.get("thread_pitch_mm") == 1.25
    saved = library.add_tool(dialog.values())
    snapshot = library.tool_snapshot(saved["id"])
    assert snapshot["thread_pitch_mm"] == 1.25 and snapshot["tap_type"] == "Cutting tap"

    # An older tap that only has its size in the name opens with the boxes filled.
    old = library.add_tool({"display_name": "M8 spiral tap", "tool_type": "Tap", "diameter_mm": 8})
    panel = ToolPanel(library)
    panel.load(library.get_tool(old["id"]))
    assert panel.get("thread_size") == "M8" and panel.get("thread_pitch_mm") == 1.25
    assert panel.get("display_name") == "M8 spiral tap" and not panel.dirty
    dialog.close()


def test_insert_cutter_links_or_creates_its_insert_on_the_same_screen(qapp, library):
    dialog = AddToolDialog([], None, {"tool_type": "Face Mill"}, library)
    panel = dialog.panel
    assert {"insert_count", "linked_insert_id", "approach_angle_deg"} <= panel.visible_keys()
    assert "tool_material" not in panel.visible_keys() and "flute_count" not in panel.visible_keys()
    assert not panel.new_insert_button.isHidden()
    insert_dialog = AddInsertDialog(library)
    insert_dialog.panel.widgets["manufacturer"].setCurrentText("WIDIA")
    insert_dialog.panel.widgets["designation"].setText("SEHT1204")
    insert_dialog.panel.widgets["grade"].setText("WP25PM")
    assert insert_dialog.values()["display_name"] == "WIDIA SEHT1204 WP25PM"
    saved_insert = panel.select_new_insert(insert_dialog.values())
    panel.widgets["diameter_mm"].setValue(50)
    panel.widgets["insert_count"].setValue(4)
    values = dialog.values()
    assert values["linked_insert_id"] == saved_insert["id"]
    assert values["display_name"] == "50mm 4-Tip Face Mill"
    saved = library.add_tool(values)
    assert library.tool_snapshot(saved["id"])["insert"]["grade"] == "WP25PM"
    assert "WIDIA" in library.list_manufacturers()
    # Without a library (no place to save an insert) the button is not offered.
    assert ToolPanel(None).new_insert_button.isHidden()
    dialog.close()
    insert_dialog.close()


def test_size_lists_and_adding_a_set(qapp, library, dialog):
    assert parse_size_list("5, 6.8, 8.5mm, 5", "Drill") == ([{"diameter_mm": 5.0}, {"diameter_mm": 6.8}, {"diameter_mm": 8.5}], [])
    sizes, rejected = parse_size_list("M6 m8 10 M12 x 1.25 big", "Tap")
    assert [(item["thread_size"], item["thread_pitch_mm"]) for item in sizes] == [("M6", 1.0), ("M8", 1.25), ("M10", 1.5), ("M12", 1.25)]
    assert rejected == ["big"]

    chooser = AddSetDialog(library)
    assert "Face Mill" not in chooser.TYPES and "Drill" in chooser.TYPES
    chooser.tool_type.setCurrentText("Tap")
    assert chooser.flutes.isHidden()
    assert not chooser.buttons.button(chooser.buttons.StandardButton.Save).isEnabled()
    chooser.sizes.setText("M6, M8, M10x1.25, nope")
    chooser.material.setCurrentText("HSS-Co / Cobalt")
    chooser.coating.setCurrentText("TiN")
    assert "Will add 3 tools" in chooser.preview.text() and "nope" in chooser.preview.text()
    tools = chooser.tools()
    assert [tool["display_name"] for tool in tools] == ["M6 x 1 HSS-Co Tap", "M8 x 1.25 HSS-Co Tap", "M10 x 1.25 HSS-Co Tap"]
    assert tools[0]["details"] == {"thread_size": "M6", "thread_pitch_mm": 1.0, "tap_type": "Cutting tap"}

    before = len(library.list_tools())
    dialog._create_set(tools)
    assert len(library.list_tools()) == before + 3
    assert library.get_tool(dialog._current["tool"])["display_name"] == "M10 x 1.25 HSS-Co Tap"
    assert dialog.panels["tool"].get("coating") == "TiN"

    chooser.tool_type.setCurrentText("End Mill")
    assert not chooser.flutes.isHidden() and chooser.flutes.value() == 4
    chooser.sizes.setText("6 10")
    assert [tool["display_name"] for tool in chooser.tools()] == ["6mm 4-Flute Carbide End Mill", "10mm 4-Flute Carbide End Mill"]
    chooser.close()


def test_library_edits_in_place_and_only_saves_real_changes(qapp, library, dialog):
    table = dialog.tables["tool"]
    assert [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())] == ["Name", "Type", "Size", "Material", "Coating", "Review"]
    assert dialog._current["tool"] is None and not dialog._editors["tool"].isVisible()

    tool_id = _select(dialog, "tool", "16mm Carbide 4-Flute End Mill")
    panel = dialog.panels["tool"]
    assert dialog._editors["tool"].isVisible()
    assert panel.get("diameter_mm") == 16 and panel.get("flute_count") == 4
    before = library.get_tool(tool_id)

    # Looking at other tools writes nothing.
    _select(dialog, "tool", "25 Tipped")
    _select(dialog, "tool", "16mm Carbide 4-Flute End Mill")
    assert library.get_tool(tool_id)["revision"] == before["revision"]

    panel.widgets["coating"].setCurrentText("AlTiN")
    panel.widgets["needs_review"].setChecked(False)
    panel.committed.emit()
    saved = library.get_tool(tool_id)
    assert saved["coating"] == "AlTiN" and saved["needs_review"] is False
    assert saved["display_name"] == "16mm Carbide 4-Flute End Mill"
    assert saved["notes"] == before["notes"] and saved["revision"] == before["revision"] + 1
    assert saved["field_provenance"]["coating"]["status"] == "user_supplied"
    assert dialog.status["tool"].text() == "Saved"
    assert dialog._current["tool"] == tool_id
    row = table.currentRow()
    assert table.item(row, 4).text() == "AlTiN" and table.item(row, 5).text() == ""

    # A second commit with nothing new does not bump the record again.
    panel.committed.emit()
    assert library.get_tool(tool_id)["revision"] == saved["revision"]

    # An unsaved change is written when another tool is picked or the window closes.
    panel.widgets["default_stickout_mm"].setValue(45)
    _select(dialog, "tool", "25 Tipped")
    assert library.get_tool(tool_id)["default_stickout_mm"] == 45
    tipped = dialog._current["tool"]
    dialog.panels["tool"].widgets["insert_count"].setValue(3)
    dialog.done(0)
    assert library.get_tool(tipped)["insert_count"] == 3


def test_filter_sorting_duplicate_and_delete(qapp, library, dialog):
    table = dialog.tables["tool"]
    dialog._create("tool", {"display_name": "5mm Drill", "tool_type": "Drill", "diameter_mm": 5})
    dialog._create("tool", {"display_name": "12mm Drill", "tool_type": "Drill", "diameter_mm": 12})
    dialog.type_filter.setCurrentText("Drills")
    assert sorted(table.item(row, 0).text() for row in range(table.rowCount())) == ["12mm Drill", "5mm Drill"]
    table.sortItems(2)
    assert [table.item(row, 0).text() for row in range(table.rowCount())] == ["5mm Drill", "12mm Drill"]

    # A new record is shown even when the current filter would hide it.
    created = dialog._create("tool", {"display_name": "M6 Tap", "tool_type": "Tap", "diameter_mm": 6})
    assert dialog.type_filter.currentText() == "All tools"
    assert dialog._current["tool"] == created["id"]

    dialog._duplicate()
    copy_id = dialog._current["tool"]
    assert copy_id != created["id"] and library.get_tool(copy_id)["display_name"] == "M6 Tap (copy)"
    dialog._remove("tool", copy_id)
    assert library.get_tool(copy_id) is None and dialog._current["tool"] is None

    dialog.tabs.setCurrentIndex(1)
    insert_id = _select(dialog, "insert", "WIDIA XDPT17 WP25PM")
    insert_panel = dialog.panels["insert"]
    assert isinstance(insert_panel, InsertPanel) and insert_panel.get("corner_radius_mm") == 0.8
    insert_panel.widgets["coating"].setCurrentText("TiAlN")
    insert_panel.committed.emit()
    assert library.get_insert(insert_id)["coating"] == "TiAlN"
    assert library.get_insert(insert_id)["display_name"] == "WIDIA XDPT17 WP25PM"
