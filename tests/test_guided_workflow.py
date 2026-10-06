import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.cutdata_ai.config.constants import PROMPT_VERSION, SCHEMA_VERSION
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import MachiningRequest, MachiningResult, MachineProfile
from src.cutdata_ai.models.schema import StructuredResponseError, result_from_json
from src.cutdata_ai.services.calculation_service import CalculationService, validate_and_correct_result
from src.cutdata_ai.services.normalization import normalize_request, request_hash
from src.cutdata_ai.services.openai_service import MockOpenAIService
from src.cutdata_ai.services.tool_library import ToolLibraryService
from src.cutdata_ai.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path):
    value = MainWindow(Database(tmp_path / "guided.sqlite3"))
    yield value
    value.close()
    value.deleteLater()
    qapp.processEvents()


def _select_temporary(window, tool_type, diameter=10.0):
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData("temporary"))
    window.temporary_tool_type.setCurrentText(tool_type)
    window.temporary_diameter.setValue(diameter)


def test_guided_is_default_and_25_tipped_builds_profile_request_without_doc(window):
    assert window.workflow_mode == "guided"
    library = ToolLibraryService(window.database)
    tool = next(item for item in library.list_tools() if item["display_name"] == "25 Tipped")
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tool["id"]))
    window.guided_job_type.setCurrentText("Profile / outside contour")
    window.job_depth.setValue(50)
    window.stock_on_side.setValue(3)

    request = window._collect_request()
    assert request.workflow_mode == "guided"
    assert request.operation == "AI Guided"
    assert request.tool_type == "Indexable End Mill"
    assert request.parameters["diameter_mm"] == 25
    assert request.parameters["insert_count"] == 2
    assert request.parameters["insert_designation"] == "XDPT170408PESRMM"
    assert request.parameters["insert_grade"] == "WP25PM"
    assert request.parameters["job_depth_mm"] == 50
    assert request.parameters["material_thickness_mm"] == 50
    assert request.parameters["stock_on_side_mm"] == 3
    assert "axial_doc_mm" not in request.parameters
    assert "radial_doc_mm" not in request.parameters
    assert request.tool_snapshot["insert"]["grade"] == "WP25PM"

    outcome = CalculationService(window.database, MockOpenAIService()).calculate(request, window._machine())
    assert outcome.source == "mock"
    assert outcome.result.recommended_operation
    assert outcome.result.recommended_strategy.startswith("DEVELOPMENT MOCK")
    assert outcome.result.recommended_pass_count == 1
    assert outcome.result.pass_plan[0]["passes"] == 1
    assert "not a production recommendation" in outcome.result.notes[0].casefold()


def test_job_type_shows_only_relevant_inputs_and_preserves_switched_values(window, qapp):
    window.show()
    window.guided_job_type.setCurrentText("Profile / outside contour")
    qapp.processEvents()
    assert window.job_depth.isVisible()
    assert window.stock_on_side.isVisible()
    assert not window.hole_depth.isVisible()
    window.job_depth.setValue(12)
    window.stock_on_side.setValue(1)

    window.guided_job_type.setCurrentText("Drill hole")
    qapp.processEvents()
    assert window.hole_depth.isVisible()
    assert not window.hole_diameter.isVisible()
    assert not window.job_depth.isVisible()
    assert not window.stock_on_side.isVisible()
    window.hole_depth.setValue(20)

    _select_temporary(window, "Drill")
    assert window.guided_job_type.currentText() == "Drill hole"
    drilling = window._collect_request().parameters
    assert drilling["hole_depth_mm"] == 20
    assert "job_depth_mm" not in drilling
    assert "stock_on_side_mm" not in drilling

    tool = next(item for item in ToolLibraryService(window.database).list_tools() if item["display_name"] == "25 Tipped")
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tool["id"]))
    # An indexable end mill cannot drill, so the job falls back to milling.
    assert window.guided_job_type.findText("Drill hole") == -1
    window.guided_job_type.setCurrentText("Profile / outside contour")
    qapp.processEvents()
    assert window.job_depth.isVisible()
    assert window.job_depth.value() == 12
    profile = window._collect_request().parameters
    assert profile["job_depth_mm"] == 12
    assert "hole_depth_mm" not in profile


def test_advanced_overrides_only_apply_when_enabled_and_relevant(window):
    tool = next(item for item in ToolLibraryService(window.database).list_tools() if item["display_name"] == "25 Tipped")
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tool["id"]))
    window.advanced_fields["max_axial_doc_mm"].setValue(2)
    window.advanced_fields["max_rpm"].setValue(1500)
    assert "constraints" not in window._collect_request().parameters

    window.guided_advanced_group.setChecked(True)
    profile = window._collect_request().parameters["constraints"]
    assert profile["max_axial_doc_mm"] == 2
    assert profile["max_rpm"] == 1500

    _select_temporary(window, "Drill")
    window.guided_job_type.setCurrentText("Drill hole")
    drilling = window._collect_request().parameters["constraints"]
    assert "max_axial_doc_mm" not in drilling
    assert drilling["max_rpm"] == 1500
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tool["id"]))
    window.guided_job_type.setCurrentText("Profile / outside contour")
    assert window._collect_request().parameters["constraints"]["max_axial_doc_mm"] == 2


def test_calculation_reports_research_validation_and_finishing_stages(window):
    progress = []
    tool = next(item for item in ToolLibraryService(window.database).list_tools() if item["display_name"] == "25 Tipped")
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tool["id"]))
    request = window._collect_request()
    CalculationService(window.database, MockOpenAIService(), progress.append).calculate(request, window._machine())
    assert any("Researching" in stage for stage in progress)
    assert any("Validating" in stage for stage in progress)
    assert progress[-1] == "Finishing the result"


def test_guided_hardness_is_limited_to_materials_that_accept_it(window):
    library = ToolLibraryService(window.database)
    tool = next(item for item in library.list_tools() if item["display_name"] == "25 Tipped")
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tool["id"]))

    # A persisted value can survive from an earlier material; normalize it
    # when the window restores a material that has no hardness field.
    window.hardness.setValue(60)
    window._update_material_fields()
    assert window.hardness.value() == 0
    assert window._collect_request().hardness_hrc is None

    window.material_combo.setCurrentText("Toolox 44")
    window.hardness.setValue(60)
    assert window._collect_request().hardness_hrc == 60

    window.material_combo.setCurrentText("Mild Steel")
    assert window.hardness.value() == 0
    assert window._collect_request().hardness_hrc is None

    window.material_combo.setCurrentText("Custom / Other")
    window.hardness.setValue(38)
    assert window._collect_request().hardness_hrc == 38


def test_advanced_manual_workflow_remains_available(window):
    window.workflow_combo.setCurrentIndex(window.workflow_combo.findData("manual"))
    window.tool_combo.setCurrentText("End Mill")
    window.pages["end_mill"].fields["diameter_mm"].setValue(12)
    window.pages["end_mill"].fields["flute_count"].setValue(4)

    request = window._collect_request()
    assert window.workflow_mode == "manual"
    assert request.workflow_mode == "manual"
    assert request.parameters["diameter_mm"] == 12
    assert request.parameters["flute_count"] == 4
    assert request.operation != "AI Guided"


def test_explicit_numeric_maximums_are_enforced_on_headline_and_pass_plan():
    request = MachiningRequest(
        "HAAS VF-2", "Mild Steel", "Indexable End Mill", "AI Guided",
        {
            "diameter_mm": 25,
            "insert_count": 2,
            "constraints": {
                "max_rpm": 1000,
                "max_feed_mm_min": 500,
                "max_axial_doc_mm": 2,
                "max_radial_engagement_mm": 3,
                "max_stepover_mm": 1.5,
            },
        },
        workflow_mode="guided",
    )
    result = MachiningResult(
        rpm=2000, feed_mm_min=1000, feed_per_tooth_mm=0.25,
        axial_doc_mm=8, radial_doc_mm=6, stepover_mm=4,
        recommended_operation="Roughing Waterline", recommended_strategy="Rough then finish",
        recommended_pass_count=2,
        pass_plan=[{
            "stage": "Rough", "passes": 2, "axial_doc_mm": 8,
            "radial_engagement_mm": 6, "stepover_mm": 4, "rpm": 2000,
            "feed_mm_min": 1000,
        }],
    )
    machine = MachineProfile("HAAS VF-2", 8000, 5000)
    corrected, _ = validate_and_correct_result(result, request, machine)

    assert corrected.rpm == 1000
    assert corrected.feed_mm_min == pytest.approx(500)
    assert corrected.axial_doc_mm == 2
    assert corrected.radial_doc_mm == 3
    assert corrected.stepover_mm == 1.5
    assert corrected.pass_plan[0]["rpm"] == 1000
    assert corrected.pass_plan[0]["feed_mm_min"] == 500
    assert corrected.pass_plan[0]["axial_doc_mm"] == 2
    assert corrected.pass_plan[0]["radial_engagement_mm"] == 3
    assert corrected.pass_plan[0]["stepover_mm"] == 1.5


def test_library_cosmetics_do_not_change_cache_identity_but_insert_facts_do(tmp_path):
    database = Database(tmp_path / "identity.sqlite3")
    library = ToolLibraryService(database)
    tool = next(item for item in library.list_tools() if item["display_name"] == "25 Tipped")

    def make_request(snapshot):
        return MachiningRequest(
            "HAAS VF-2", "Mild Steel", "Indexable End Mill", "AI Guided",
            {"diameter_mm": 25, "insert_count": 2, "job_type": "Profile"},
            workflow_mode="guided", tool_snapshot=snapshot,
        )

    original_snapshot = library.tool_snapshot(tool["id"])
    original = normalize_request(make_request(original_snapshot))
    database.add_recent(request_hash(original), original, {"rpm": 1000}, "ai", "gpt-6-luna")
    original_hash = request_hash(original)

    library.update_tool(tool["id"], {"display_name": "Shop's 25 mm VSM17"})
    renamed_snapshot = library.tool_snapshot(tool["id"])
    assert request_hash(normalize_request(make_request(renamed_snapshot))) == original_hash

    linked_insert_id = tool["linked_insert_id"]
    library.update_insert(linked_insert_id, {"grade": "WP25PM-X"})
    changed_snapshot = library.tool_snapshot(tool["id"])
    assert request_hash(normalize_request(make_request(changed_snapshot))) != original_hash
    stored = json.loads(database.recent(1)[0]["normalized_request_json"])
    assert stored["tool_snapshot"]["insert"]["grade"] == "wp25pm"


def test_schema_keeps_older_history_readable_and_checks_new_pass_contract():
    legacy = result_from_json(json.dumps({"rpm": 1000, "feed_mm_min": 100, "notes": [], "warnings": []}))
    assert legacy.recommended_operation is None
    assert legacy.pass_plan == []

    with pytest.raises(StructuredResponseError, match="positive integer"):
        result_from_json(json.dumps({
            "rpm": 1000, "feed_mm_min": 100, "recommended_pass_count": 0,
        }))
    with pytest.raises(StructuredResponseError, match="positive integer"):
        result_from_json(json.dumps({
            "rpm": 1000, "feed_mm_min": 100,
            "pass_plan": [{"stage": "Rough", "passes": 0}],
        }))
    assert PROMPT_VERSION == "2026-09-28.1"
    assert SCHEMA_VERSION == "3"


def test_pass_plan_limits_preserve_stage_chipload_and_name_the_real_limit():
    request = MachiningRequest(
        "HAAS VF-2", "Aluminium 6082", "End Mill", "AI Guided",
        {"diameter_mm": 10, "flute_count": 2, "constraints": {"max_rpm": 20000}},
        workflow_mode="guided",
    )
    result = MachiningResult(
        rpm=12000, feed_mm_min=2400, feed_per_tooth_mm=0.1,
        recommended_operation="Roughing Waterline", recommended_strategy="Rough",
        recommended_pass_count=1,
        pass_plan=[
            {"stage": "Rough", "passes": 1, "rpm": 12000, "feed_mm_min": 2400},
            {"stage": "Fast", "passes": 1, "rpm": 6000, "feed_mm_min": 15000},
        ],
    )
    machine = MachineProfile("HAAS VF-2", 8000, 10000)
    corrected, corrections = validate_and_correct_result(result, request, machine)

    assert corrected.rpm == 8000
    assert corrected.feed_mm_min == pytest.approx(1600)
    # RPM clamp scales the stage feed, so feed per tooth is unchanged.
    assert corrected.pass_plan[0]["rpm"] == 8000
    assert corrected.pass_plan[0]["feed_mm_min"] == pytest.approx(1600)
    # Feed clamp scales the stage RPM for the same reason.
    assert corrected.pass_plan[1]["feed_mm_min"] == 10000
    assert corrected.pass_plan[1]["rpm"] == pytest.approx(4000)
    # The user's 20,000 RPM maximum was not the limit that applied.
    assert any("HAAS VF-2 maximum of 8000 RPM" in item for item in corrections)
    assert not any("requested maximum" in item for item in corrections)


def test_job_types_follow_the_selected_tool_and_legacy_names_are_migrated(qapp, tmp_path):
    from src.cutdata_ai.ui.main_window import GUIDED_JOB_TYPES, guided_job_types_for_tool

    assert len(GUIDED_JOB_TYPES) == 11
    assert guided_job_types_for_tool("") == GUIDED_JOB_TYPES
    assert guided_job_types_for_tool("Reamer") == ("Ream hole", "Other / describe job")
    assert "Drill hole" not in guided_job_types_for_tool("End Mill")
    assert len(guided_job_types_for_tool("End Mill")) == 6

    database = Database(tmp_path / "legacy-job.sqlite3")
    database.set_setting("last_calculator_state", json.dumps({
        "global": {"workflow_mode": "guided"},
        "guided": {"job_type": "Steep wall / 3D wall finish", "independent_check": False},
    }))
    window = MainWindow(database)
    try:
        assert window.guided_job_type.currentText() == "3D surface / wall finish"
        assert window.surface_type.currentText() == "Steep wall"
        assert not window.independent_check.isChecked()
        _select_temporary(window, "Tap")
        items = [window.guided_job_type.itemText(i) for i in range(window.guided_job_type.count())]
        assert items == ["Tap thread", "Other / describe job"]
        assert window.guided_job_type.currentText() == "Tap thread"
        # The placeholder result follows the selected tool.
        assert not window.result_cards["tap_drill_mm"].isHidden()
        assert window.result_cards["axial_doc_mm"].isHidden()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_setup_details_are_collapsed_but_still_sent(window, qapp):
    window.show()
    qapp.processEvents()
    assert not window.guided_coolant.isVisible()
    assert window.finish_requirement.isVisible()
    window.guided_coolant.setCurrentText("Mist")
    window.setup_stickout.setValue(60)
    assert "Mist" in window.optional_toggle.text() and "stickout 60 mm" in window.optional_toggle.text()
    tool = next(item for item in ToolLibraryService(window.database).list_tools() if item["display_name"] == "25 Tipped")
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tool["id"]))
    parameters = window._collect_request().parameters
    assert parameters["coolant_type"] == "Mist"
    assert parameters["stickout_mm"] == 60
    window.optional_toggle.setChecked(True)
    qapp.processEvents()
    assert window.guided_coolant.isVisible()


def test_recent_guided_calculation_refills_the_guided_form(window, qapp):
    tool = next(item for item in ToolLibraryService(window.database).list_tools() if item["display_name"] == "25 Tipped")
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tool["id"]))
    window.guided_job_type.setCurrentText("Pocket / cavity")
    window.pocket_depth.setValue(18)
    window.guided_coolant.setCurrentText("Mist")
    window.guided_advanced_group.setChecked(True)
    window.advanced_fields["max_rpm"].setValue(1500)
    request = window._collect_request()
    normalized = normalize_request(request)
    result = MachiningResult(
        rpm=900, feed_mm_min=180, feed_per_tooth_mm=0.1,
        recommended_operation="Roughing Waterline", recommended_strategy="Rough the pocket",
        recommended_pass_count=1, pass_plan=[{"stage": "Rough", "passes": 1}],
    )
    window.database.add_recent(request_hash(normalized), normalized, result.to_dict(), "ai", model="gpt-6-luna")

    # Change everything, including the workflow, then reopen the record.
    window.guided_tool_combo.setCurrentIndex(0)
    window.pocket_depth.setValue(0)
    window.guided_coolant.setCurrentText("Flood coolant")
    window.guided_advanced_group.setChecked(False)
    window.advanced_fields["max_rpm"].setValue(0)
    window.workflow_combo.setCurrentIndex(1)
    window._load_recent()
    window._load_recent_item(window.recent_list.item(0))

    assert window.workflow_mode == "guided"
    assert window.guided_tool_combo.currentData() == tool["id"]
    assert window.guided_job_type.currentText() == "Pocket / cavity"
    assert window.pocket_depth.value() == 18
    assert window.guided_coolant.currentText() == "Mist"
    assert window.guided_advanced_group.isChecked()
    assert window.advanced_fields["max_rpm"].value() == 1500
    assert window.result_fields["rpm"].text() == "900 RPM"
    assert request_hash(normalize_request(window._collect_request())) == request_hash(normalized)


def test_manual_form_can_be_filled_from_a_library_tool(window):
    tool = next(item for item in ToolLibraryService(window.database).list_tools() if item["display_name"] == "25 Tipped")
    window.workflow_combo.setCurrentIndex(1)
    window.manual_library_combo.setCurrentIndex(window.manual_library_combo.findData(tool["id"]))
    window._fill_manual_from_library()

    assert window.tool_combo.currentText() == "Indexable End Mill"
    request = window._collect_request()
    assert request.workflow_mode == "manual"
    assert request.parameters["cutter_diameter_mm"] == 25
    assert request.parameters["insert_count"] == 2
    assert request.parameters["insert_code"] == "XDPT170408PESRMM"
    assert request.parameters["insert_grade"] == "WP25PM"


def _add_and_select(window, **values):
    tool = ToolLibraryService(window.database).add_tool(values)
    window._refresh_guided_tools()
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tool["id"]))
    return tool


def _visible_job_fields(window):
    return {key for key, (label, _widget) in window.guided_rows.items() if not label.isHidden()}


def test_library_drill_offers_pilot_hole_material_and_coating(window, qapp):
    from src.cutdata_ai.services.calculation_service import validate_request

    window.show()
    tool = _add_and_select(
        window, display_name="20mm Drill", tool_type="Drill", diameter_mm=20,
        tool_material="HSS-Co / Cobalt", coating="TiN",
    )
    qapp.processEvents()
    assert window.guided_job_type.currentText() == "Drill hole"
    assert window.guided_material.isVisible() and window.guided_coating.isVisible()
    assert window.guided_material.currentText() == "HSS-Co / Cobalt"
    assert window.guided_coating.currentText() == "TiN"
    assert window.guided_material.findText("Indexable") >= 0
    assert window.pilot_hole.isVisible() and window.hole_type.isVisible()
    assert not window.hole_diameter.isVisible() and not window.entry_access.isVisible()

    window.hole_depth.setValue(40)
    window.pilot_hole.setValue(8)
    window.hole_type.setCurrentText("Blind hole")
    request = window._collect_request()
    assert request.parameters["existing_pilot_hole_diameter_mm"] == 8
    assert request.parameters["hole_type"] == "Blind hole"
    assert request.parameters["tool_material"] == "HSS-Co / Cobalt"
    assert request.parameters["coating"] == "TiN"
    assert "hole_diameter_mm" not in request.parameters
    assert request.tool_snapshot == ToolLibraryService(window.database).tool_snapshot(tool["id"])
    assert validate_request(request, window._machine())[0] == []

    # A change on the form applies to this job only.
    window.guided_material.setCurrentText("Carbide")
    window.guided_coating.setCurrentText("Unknown")
    request = window._collect_request()
    assert request.parameters["tool_material"] == "Carbide"
    assert request.parameters["coating"] == "Unknown"
    assert request.tool_snapshot["tool_material"] == "Carbide"
    assert request.tool_snapshot["field_provenance"]["tool_material"]["status"] == "user_supplied"
    stored = ToolLibraryService(window.database).get_tool(tool["id"])
    assert stored["tool_material"] == "HSS-Co / Cobalt" and stored["coating"] == "TiN"

    # Reopening the library keeps the choice; picking another tool resets it.
    window._refresh_guided_tools()
    assert window.guided_material.currentText() == "Carbide"
    other = _add_and_select(window, display_name="12mm Drill", tool_type="Drill", diameter_mm=12)
    assert window.guided_material.currentText() == "Unknown"
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tool["id"]))
    assert window.guided_material.currentText() == "HSS-Co / Cobalt"
    assert other["id"] != tool["id"]

    window.pilot_hole.setValue(20)
    errors, _warnings = validate_request(window._collect_request(), window._machine())
    assert "Pilot hole must be smaller than the drill diameter." in errors

    window.pilot_hole.setValue(0)
    assert "existing_pilot_hole_diameter_mm" not in window._collect_request().parameters


def test_each_tool_shows_only_its_own_boxes(window, qapp):
    window.show()
    common = {"coolant_type", "cut_priority", "stock_condition", "stickout_mm", "setup_rigidity", "setup_notes"}
    expected = {
        "Drill": {"hole_depth_mm", "hole_type", "existing_pilot_hole_diameter_mm"},
        "Reamer": {"hole_depth_mm", "hole_type", "existing_hole_diameter_mm"},
        "Tap": {"thread_size", "pitch_mm", "thread_depth_mm", "hole_type", "tap_type"},
        "Thread Mill": {"thread_size", "pitch_mm", "thread_depth_mm", "hole_type", "existing_hole_diameter_mm", "entry_access"},
        "Chamfer Mill": {"chamfer_size_mm", "hole_diameter_mm", "entry_access"},
    }
    for tool_type, fields in expected.items():
        _add_and_select(window, display_name=f"Test {tool_type}", tool_type=tool_type, diameter_mm=10, tool_material="HSS")
        qapp.processEvents()
        assert _visible_job_fields(window) == fields | common, tool_type
        assert window.guided_material.isVisible(), tool_type
        assert window.guided_material.currentText() == "HSS", tool_type

    # A spot drill asked to drill has no pilot hole.
    _add_and_select(window, display_name="Spot", tool_type="Spot Drill / Centre Drill", diameter_mm=10)
    window.guided_job_type.setCurrentText("Drill hole")
    assert _visible_job_fields(window) == {"hole_depth_mm"} | common

    # Insert cutters take grade and coating from the linked insert.
    tipped = next(item for item in ToolLibraryService(window.database).list_tools() if item["display_name"] == "25 Tipped")
    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(tipped["id"]))
    qapp.processEvents()
    assert not window.guided_material.isVisible() and not window.guided_coating.isVisible()
    assert window._collect_request().tool_snapshot == ToolLibraryService(window.database).tool_snapshot(tipped["id"])

    window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData("temporary"))
    qapp.processEvents()
    assert not window.guided_material.isVisible()
    assert window.temporary_material.isVisible()


def test_selecting_a_tap_fills_thread_size_and_pitch(window, qapp):
    _add_and_select(window, display_name="M10 Spiral Tap", tool_type="Tap", diameter_mm=10, tool_material="HSS-Co / Cobalt")
    assert window.guided_job_type.currentText() == "Tap thread"
    assert window.thread_size.text() == "M10"
    assert window.thread_pitch.value() == 1.5
    window.thread_depth.setValue(18)
    request = window._collect_request()
    assert request.parameters["thread_size"] == "M10"
    assert request.parameters["pitch_mm"] == 1.5
    assert request.parameters["tap_type"] == "Cutting tap"
    assert request.parameters["hole_type"] == "Through hole"
    assert "hole_diameter_mm" not in request.parameters

    # A user's pitch survives a library refresh of the same tool.
    window.thread_pitch.setValue(1.0)
    window._refresh_guided_tools()
    assert window.thread_pitch.value() == 1.0

    _add_and_select(window, display_name="Fine tap M12x1.25", tool_type="Tap", diameter_mm=12)
    assert (window.thread_size.text(), window.thread_pitch.value()) == ("M12", 1.25)

    _add_and_select(window, display_name="Tap, size by diameter", tool_type="Tap", diameter_mm=8)
    assert (window.thread_size.text(), window.thread_pitch.value()) == ("M8", 1.25)

    recorded = _add_and_select(
        window, display_name="Recorded tap", tool_type="Tap", diameter_mm=16,
        details={"thread_size": "M16", "thread_pitch_mm": 1.5},
    )
    assert (window.thread_size.text(), window.thread_pitch.value()) == ("M16", 1.5)
    assert window._collect_request().tool_snapshot["thread_pitch_mm"] == 1.5
    assert recorded["details"]["thread_size"] == "M16"

    # Typing a size by hand sets the standard pitch.
    _select_temporary(window, "Tap", 6)
    window.thread_size.setText("")
    window.thread_size.textEdited.emit("M6")
    assert window.thread_pitch.value() == 1.0


def test_metric_thread_helpers_and_pilot_prompt_note():
    from src.cutdata_ai.config.constants import metric_thread_for_tool, metric_thread_from_text, tool_materials_for
    from src.cutdata_ai.prompts.machining import build_user_prompt

    assert metric_thread_from_text("M10") == ("M10", None)
    assert metric_thread_from_text("hss m8 x 1.0 tap") == ("M8", 1.0)
    assert metric_thread_from_text("10mm WIDIA W401M10005SZT") is None
    assert metric_thread_from_text("16mm Carbide") is None
    assert metric_thread_for_tool({"display_name": "Odd tap", "diameter_mm": 11}) == ("", None)
    assert metric_thread_for_tool({"thread_size": "M10x1.25"}) == ("M10x1.25", 1.25)
    assert tool_materials_for("Face Mill") == ()
    assert "Indexable" in tool_materials_for("Drill")

    machine = MachineProfile(name="Test", max_rpm=8000, max_feed_mm_min=5000)
    parameters = {"diameter_mm": 20, "hole_depth_mm": 40, "job_type": "Drill hole"}
    plain = MachiningRequest(machine="Test", material="Mild Steel", tool_type="Drill", operation="AI Guided", parameters=dict(parameters), workflow_mode="guided")
    assert "request_notes" not in build_user_prompt(plain, machine)
    piloted = MachiningRequest(machine="Test", material="Mild Steel", tool_type="Drill", operation="AI Guided", parameters=dict(parameters, existing_pilot_hole_diameter_mm=8), workflow_mode="guided")
    assert "already pilot-drilled to 8 mm" in build_user_prompt(piloted, machine)


def test_tool_overrides_and_new_boxes_survive_restart_and_recent(qapp, tmp_path):
    database = Database(tmp_path / "persist.sqlite3")
    first = MainWindow(database)
    tool = _add_and_select(first, display_name="20mm Drill", tool_type="Drill", diameter_mm=20, tool_material="HSS", coating="TiN")
    first.guided_material.setCurrentText("Carbide")
    first.pilot_hole.setValue(8)
    first.hole_depth.setValue(40)
    request = first._collect_request()
    outcome = CalculationService(database, MockOpenAIService()).calculate(request, first._machine())
    first._save_calculator_state()
    first.close()
    first.deleteLater()
    qapp.processEvents()

    second = MainWindow(database)
    try:
        assert second.guided_tool_combo.currentData() == tool["id"]
        assert second.guided_material.currentText() == "Carbide"
        assert second.guided_coating.currentText() == "TiN"
        assert second.pilot_hole.value() == 8

        second.guided_material.setCurrentText("HSS")
        second.pilot_hole.setValue(0)
        second._load_guided_inputs(outcome.normalized_request)
        assert second.guided_material.currentText() == "Carbide"
        assert second.pilot_hole.value() == 8
        assert second.hole_depth.value() == 40
    finally:
        second.close()
        second.deleteLater()
        qapp.processEvents()


def test_guided_hole_result_without_pass_count_or_plan_is_accepted():
    machine = MachineProfile("HAAS VF-2", 8000, 5000)

    def guided(tool_type, **parameters):
        return MachiningRequest(
            machine="HAAS VF-2", material="Mild Steel", tool_type=tool_type, operation="AI Guided",
            parameters=dict(parameters, diameter_mm=20), workflow_mode="guided",
        )

    drill = MachiningResult(
        rpm=600, feed_mm_min=120, feed_per_rev_mm=0.2, peck_recommended=False,
        recommended_operation="Drilling", recommended_strategy="Open out the pilot hole",
    )
    corrected, _ = validate_and_correct_result(drill, guided("Drill", hole_depth_mm=40), machine)
    assert corrected.recommended_pass_count == 1
    assert corrected.pass_plan[0]["rpm"] == 600 and corrected.pass_plan[0]["feed_mm_min"] == 120

    # A plan without a total is counted from its stages.
    planned = MachiningResult(
        rpm=2000, feed_mm_min=800, feed_per_tooth_mm=0.1,
        recommended_operation="Roughing Waterline", recommended_strategy="Rough then finish",
        pass_plan=[{"stage": "Rough", "passes": 3, "rpm": 2000, "feed_mm_min": 800},
                   {"stage": "Finish", "passes": None, "rpm": 2000, "feed_mm_min": 600}],
    )
    corrected, _ = validate_and_correct_result(planned, guided("End Mill", flute_count=4), machine)
    assert corrected.recommended_pass_count == 3

    # Milling still needs a plan from the AI.
    bare = MachiningResult(
        rpm=2000, feed_mm_min=800, feed_per_tooth_mm=0.1,
        recommended_operation="Roughing Waterline", recommended_strategy="Rough",
    )
    with pytest.raises(StructuredResponseError):
        validate_and_correct_result(bare, guided("End Mill", flute_count=4), machine)
