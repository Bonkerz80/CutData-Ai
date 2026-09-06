import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.cutdata_ai.config.operations import (
    ENCY_OPERATIONS,
    FINISHING_WATERLINE,
    FLAT_LAND_FINISHING,
    ROUGHING_WATERLINE,
    default_operation_for_tool,
    operations_for_tool,
)
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import MachiningRequest
from src.cutdata_ai.services.normalization import normalize_request, request_hash
from src.cutdata_ai.services.recent_summary import build_recent_summary
from src.cutdata_ai.services.settings_service import SettingsService
from src.cutdata_ai.ui.main_window import MainWindow


def close_widget(widget, app):
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_ency_operation_lists_and_defaults_are_tool_specific():
    assert operations_for_tool("End Mill") == ENCY_OPERATIONS
    assert operations_for_tool("Ball Nose End Mill") == (
        ROUGHING_WATERLINE,
        FINISHING_WATERLINE,
        "Finishing Plane",
    )
    assert operations_for_tool("Bull Nose / Corner Radius End Mill") == (
        ROUGHING_WATERLINE,
        FINISHING_WATERLINE,
        "Finishing Plane",
        FLAT_LAND_FINISHING,
    )
    assert operations_for_tool("Face Mill") == ("Face Milling",)
    assert operations_for_tool("Indexable End Mill") == (
        ROUGHING_WATERLINE,
        "Face Milling",
        FLAT_LAND_FINISHING,
    )
    assert operations_for_tool("Thread Mill")[0] == "Slotting"
    assert default_operation_for_tool("End Mill") == ROUGHING_WATERLINE
    assert default_operation_for_tool("Ball Nose End Mill") == FINISHING_WATERLINE
    assert default_operation_for_tool("Bull Nose / Corner Radius End Mill") == ROUGHING_WATERLINE
    assert default_operation_for_tool("Face Mill") == "Face Milling"
    assert default_operation_for_tool("Indexable End Mill") == ROUGHING_WATERLINE


def test_operation_fields_and_last_used_choice_follow_tool(tmp_path):
    app = QApplication.instance() or QApplication([])
    database = Database(Path(tmp_path) / "operations.sqlite3")
    window = MainWindow(database)
    try:
        window.tool_combo.setCurrentText("End Mill")
        page = window.pages["end_mill"]
        operation = page.fields["operation"]
        assert [operation.itemText(i) for i in range(operation.count())] == list(ENCY_OPERATIONS)
        operation.setCurrentText(FLAT_LAND_FINISHING)
        assert page.rows["radial_doc_mm"][0].text() == "Stepover (mm)"
        assert page.rows["stock_remaining_mm"][0].text().startswith("Finishing stock")
        assert page.rows["axial_doc_mm"][0].isHidden()

        window.tool_combo.setCurrentText("Ball Nose End Mill")
        assert page.fields["operation"].currentText() == FINISHING_WATERLINE
        assert page.rows["axial_doc_mm"][0].text().startswith("Z step")
        assert page.rows["radial_doc_mm"][0].isHidden()
        assert not page.rows["stock_remaining_mm"][0].isHidden()

        window.tool_combo.setCurrentText("End Mill")
        assert page.fields["operation"].currentText() == FLAT_LAND_FINISHING
    finally:
        close_widget(window, app)


def test_legacy_operation_state_reopens_without_silent_mapping(tmp_path):
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "legacy-operation.sqlite3")
    SettingsService(database).save_json_setting(
        "last_calculator_state",
        {
            "version": 1,
            "global": {"tool_type": "End Mill", "operation": "Profiling"},
            "families": {"end_mill": {"operation": "Profiling"}},
        },
    )
    window = MainWindow(database)
    try:
        assert window.tool_combo.currentText() == "End Mill"
        assert window.pages["end_mill"].fields["operation"].currentText() == "Profiling"
        assert "Profiling" in [
            window.pages["end_mill"].fields["operation"].itemText(i)
            for i in range(window.pages["end_mill"].fields["operation"].count())
        ]
    finally:
        close_widget(window, app)


def test_operation_changes_request_hash_and_recent_summary_labels():
    base = dict(
        machine="Generic CNC Mill",
        material="Mild Steel",
        custom_material="",
        hardness_hrc=None,
        tool_type="End Mill",
        parameters={"diameter_mm": 12, "flute_count": 4, "axial_doc_mm": 3, "radial_doc_mm": 2, "stock_remaining_mm": 0.5},
    )
    rough = normalize_request(MachiningRequest(operation=ROUGHING_WATERLINE, **base))
    finish = normalize_request(MachiningRequest(operation=FLAT_LAND_FINISHING, **base))
    assert request_hash(rough) != request_hash(finish)
    title, detail = build_recent_summary(rough)
    assert "Roughing Waterline" in detail
    assert "depth step" in detail
    assert "radial engagement / stepover" in detail
    assert "2026-" not in f"{title} {detail}"
