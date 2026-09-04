import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLabel, QPushButton

from src.cutdata_ai.config.constants import TOOL_TYPES, compatible_tool_type, tool_family
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import CalculationOutcome, MachiningResult
from src.cutdata_ai.services.recent_summary import build_recent_summary, recent_item_text
from src.cutdata_ai.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path):
    value = MainWindow(Database(tmp_path / "workflow.sqlite3"))
    value.show()
    qapp.processEvents()
    yield value
    value.close()
    value.deleteLater()
    qapp.processEvents()


def normalized_request(tool_type, parameters, *, material="Mild Steel", operation="Profiling"):
    return {
        "machine": "generic cnc mill",
        "material": material.casefold(),
        "custom_material": "",
        "hardness_hrc": None,
        "tool_type": tool_type.casefold(),
        "operation": operation.casefold(),
        "parameters": {
            key: value.casefold() if isinstance(value, str) else value
            for key, value in parameters.items()
        },
        "unit_system": "metric",
    }


def outcome(normalized, result, *, source="ai"):
    return CalculationOutcome(
        result=result,
        normalized_request=normalized,
        request_hash="exact-test-hash",
        source=source,
        cache_hit=source == "cache",
        model="test-model",
        validated_response=json.dumps(result.to_dict()),
    )


@pytest.mark.parametrize(
    ("tool_type", "parameters", "material", "operation", "expected_title", "expected_detail"),
    [
        (
            "Drill",
            {"diameter_mm": 22, "tool_material": "HSS", "hole_depth_mm": 160, "existing_pilot_hole_diameter_mm": 8, "flood_coolant": True},
            "Mild Steel",
            "Drilling",
            "Ø22 HSS Drill · Mild Steel",
            "160 mm deep · Ø8 pilot · Flood",
        ),
        (
            "End Mill",
            {"diameter_mm": 16, "tool_material": "Carbide", "flute_count": 4, "operation": "Profiling", "axial_doc_mm": 50, "radial_doc_mm": 0.25},
            "Mild Steel",
            "Profiling",
            "Ø16 Carbide 4F End Mill · Mild Steel",
            "Profiling · 50 mm DOC · 0.25 mm WOC",
        ),
        (
            "Ball Nose End Mill",
            {"diameter_mm": 8, "tool_material": "Carbide", "flute_count": 2, "operation": "Finishing", "stock_remaining_mm": 1},
            "D2 Hardened",
            "Finishing",
            "Ø8 Carbide 2F Ball Nose · D2 Hardened",
            "Finishing · 1 mm stock",
        ),
        (
            "Bull Nose / Corner Radius End Mill",
            {"diameter_mm": 12, "tool_material": "Carbide", "flute_count": 4, "corner_radius_mm": 1, "operation": "Profiling", "axial_doc_mm": 20},
            "P20",
            "Profiling",
            "Ø12 Carbide 4F Bull Nose R1 · P20",
            "Profiling · 20 mm DOC",
        ),
        (
            "Reamer",
            {"diameter_mm": 18, "tool_material": "HSS", "existing_hole_diameter_mm": 17.8, "hole_depth_mm": 30},
            "Mild Steel",
            "Reaming",
            "Ø18 HSS Reamer · Mild Steel",
            "Start Ø17.8 · 30 mm deep",
        ),
        (
            "Tap",
            {"thread_size": "M8", "pitch_mm": 1.25, "tap_type": "Cutting tap", "tool_material": "HSS", "thread_depth_mm": 15},
            "Mild Steel",
            "Tapping",
            "M8 × 1.25 Cutting Tap · Mild Steel",
            "HSS · 15 mm deep",
        ),
        (
            "Face Mill",
            {"cutter_diameter_mm": 66, "insert_count": 6, "cutter_type": "Face mill", "operation": "Facing", "axial_doc_mm": 0.5, "insert_code": "XDPT", "insert_grade": "WP25PM"},
            "Aluminium 6082",
            "Facing",
            "Ø66 Face Mill · 6 inserts · Aluminium 6082",
            "Facing · 0.5 mm DOC · XDPT / WP25PM",
        ),
        (
            "Indexable End Mill",
            {"cutter_diameter_mm": 32, "insert_count": 3, "operation": "Roughing", "axial_doc_mm": 2, "radial_doc_mm": 5, "insert_code": "XDPT", "insert_grade": "WP25PM"},
            "D2 Hardened",
            "Roughing",
            "Ø32 Indexable End Mill · 3 inserts · D2 Hardened",
            "Roughing · 2 mm DOC · 5 mm WOC · XDPT / WP25PM",
        ),
        (
            "Thread Mill",
            {"thread_size": "M35"},
            "Mild Steel",
            "Thread milling",
            "M35 Thread Mill · Mild Steel",
            "Thread Milling",
        ),
    ],
)
def test_recent_summary_is_family_aware_and_has_no_timestamp(
    tool_type, parameters, material, operation, expected_title, expected_detail
):
    normalized = normalized_request(tool_type, parameters, material=material, operation=operation)
    title, detail = build_recent_summary(normalized)

    assert title == expected_title
    assert detail == expected_detail
    assert recent_item_text(normalized) == f"{expected_title}\n{expected_detail}"
    assert "2026-" not in recent_item_text(normalized)
    assert ":" not in recent_item_text(normalized)


def test_removed_tools_are_not_active_but_old_labels_remain_compatible():
    assert "Slot Cutter" not in TOOL_TYPES
    assert "T-Slot Cutter" not in TOOL_TYPES
    assert compatible_tool_type("slot cutter") == "Indexable End Mill"
    assert compatible_tool_type("t-slot cutter") == "Indexable End Mill"
    assert tool_family("slot cutter") == "indexable"


def test_drill_result_populates_secondary_derived_notes_and_read_only_values(window, qapp):
    window.tool_combo.setCurrentText("Drill")
    window._update_tool_page()
    normalized = normalized_request(
        "Drill",
        {
            "diameter_mm": 22,
            "tool_material": "HSS",
            "hole_depth_mm": 160,
            "existing_pilot_hole_diameter_mm": 8,
            "flood_coolant": True,
        },
        operation="Drilling",
    )
    result = MachiningResult(
        rpm=2450,
        cutting_speed_m_min=169.2,
        feed_mm_min=365,
        feed_per_rev_mm=0.149,
        peck_mm=6,
        peck_recommended=True,
        recommended_cycle="G83 peck cycle",
        coolant="Flood coolant",
        confidence="high",
        notes=["Use flood coolant."],
        warnings=["Verify chip evacuation before production."],
    )

    window._show_result(outcome(normalized, result))
    qapp.processEvents()

    assert window.primary_group.isVisible()
    assert window.result_fields["rpm"].text() == "2,450 RPM"
    assert window.result_fields["feed_mm_min"].text() == "365 mm/min"
    assert window.result_fields["peck_mm"].text() == "6 mm"
    assert all(isinstance(field, QLabel) for field in window.result_fields.values())
    assert not window.result_panel.findChildren(QDoubleSpinBox)
    assert window.info_group.isVisible()
    assert window.info_labels["cutting_speed"].text() == "169.2 m/min"
    assert window.info_labels["feed_per_rev"].text() == "0.149 mm/rev"
    assert window.info_labels["cycle"].text() == "G83 peck cycle"
    assert window.info_labels["coolant"].text() == "Flood coolant"
    assert window.info_labels["confidence"].text() == "High"
    assert window.derived_group.isVisible()
    assert "7.27" in window.derived_labels["hole_ld_ratio"].text()
    assert "20.4%" in window.derived_labels["rpm_usage"].text()
    assert "3.6%" in window.derived_labels["feed_usage"].text()
    assert window.notes_group.isVisible()
    assert "Use flood coolant." in window.notes.toPlainText()
    assert "Verify chip evacuation" in window.notes.toPlainText()
    assert window.notes.toPlainText().count("Use flood coolant.") == 1


def test_milling_tap_reamer_and_indexable_results_show_applicable_fields(window, qapp):
    cases = [
        (
            "End Mill",
            normalized_request(
                "End Mill",
                {"diameter_mm": 16, "flute_count": 4, "operation": "Profiling", "axial_doc_mm": 50, "radial_doc_mm": 0.25},
            ),
            MachiningResult(rpm=3000, cutting_speed_m_min=150.8, feed_mm_min=480, feed_per_tooth_mm=0.04, axial_doc_mm=50, radial_doc_mm=0.25, stepover_mm=0.25, confidence="medium"),
            ("feed_per_tooth", "radial_engagement", "axial_doc_ratio", "mrr"),
        ),
        (
            "Reamer",
            normalized_request(
                "Reamer",
                {"diameter_mm": 18, "tool_material": "HSS", "existing_hole_diameter_mm": 17.8, "hole_depth_mm": 30},
                operation="Reaming",
            ),
            MachiningResult(rpm=700, cutting_speed_m_min=39.6, feed_mm_min=60, feed_per_rev_mm=0.086, pre_ream_size_mm=17.7, pre_ream_range_mm="17.65–17.75 mm", recommended_cycle="Constant-feed reaming cycle", confidence="high"),
            ("feed_per_rev", "pre_ream_range", "hole_ld_ratio", "rpm_usage"),
        ),
        (
            "Tap",
            normalized_request(
                "Tap",
                {"thread_size": "M8", "pitch_mm": 1.25, "tap_type": "Cutting tap", "tool_material": "HSS", "thread_depth_mm": 15},
                operation="Tapping",
            ),
            MachiningResult(rpm=1000, feed_mm_min=1250, feed_per_rev_mm=1.25, tap_pitch_mm=1.25, tap_drill_mm=6.8, coolant="Tapping oil", confidence="high"),
            ("feed_per_rev", "tap_relationship", "rpm_usage", "feed_usage"),
        ),
        (
            "Indexable End Mill",
            normalized_request(
                "Indexable End Mill",
                {"cutter_diameter_mm": 32, "insert_count": 3, "operation": "Roughing", "axial_doc_mm": 2, "radial_doc_mm": 5, "insert_code": "XDPT", "insert_grade": "WP25PM"},
                material="D2 Hardened",
                operation="Roughing",
            ),
            MachiningResult(
                rpm=1200,
                cutting_speed_m_min=120.6,
                feed_mm_min=800,
                feed_per_tooth_mm=0.1,
                axial_doc_mm=2,
                radial_doc_mm=5,
                stepover_mm=5,
                estimated_spindle_power_kw=4.2,
                estimated_spindle_torque_nm=33.4,
                engagement_description="Stable 5 mm radial engagement.",
                setup_risk="high",
                recommendation_summary="Verify rigidity before the first roughing pass.",
                coolant="Flood coolant",
                confidence="high",
            ),
            ("feed_per_tooth", "radial_engagement", "axial_doc_ratio", "mrr"),
        ),
    ]

    for tool_type, normalized, result, visible_keys in cases:
        window.tool_combo.setCurrentText(tool_type)
        window._update_tool_page()
        window._show_result(outcome(normalized, result))
        qapp.processEvents()
        for key in visible_keys:
            source = window.derived_labels.get(key) or window.info_labels.get(key)
            assert source is not None and source.isVisible() and source.text().strip()

    assert window.ai_context_group.isVisible()
    assert window.ai_context_labels["recommendation_summary"].text().startswith("Verify rigidity")
    assert window.ai_context_labels["setup_risk"].text() == "High"
    assert window.ai_context_labels["power"].text() == "4.2 kW"
    assert window.ai_context_labels["torque"].text() == "33.4 N·m"


def test_recent_list_uses_details_and_reopens_exact_record(window, qapp):
    normalized = normalized_request(
        "Drill",
        {"diameter_mm": 22, "tool_material": "HSS", "hole_depth_mm": 160, "existing_pilot_hole_diameter_mm": 8, "flood_coolant": True},
        operation="Drilling",
    )
    result = MachiningResult(rpm=2450, feed_mm_min=365, feed_per_rev_mm=0.149, coolant="Flood coolant", confidence="high")
    window.database.add_recent("exact-drill-hash", normalized, result.to_dict(), "ai")
    window._load_recent()
    qapp.processEvents()

    assert window.recent_list.count() == 1
    item = window.recent_list.item(0)
    assert "Ø22 HSS Drill · Mild Steel" in item.text()
    assert "160 mm deep · Ø8 pilot · Flood" in item.text()
    row = item.data(Qt.UserRole)
    assert row["created_at"][:16].replace("T", " ") not in item.text()

    window._load_recent_item(item)
    qapp.processEvents()

    assert window.tool_combo.currentText() == "Drill"
    assert window.pages["drill"].fields["diameter_mm"].value() == 22
    assert window._current_outcome is not None
    assert window._current_outcome.request_hash == "exact-drill-hash"
    assert window.result_fields["rpm"].text() == "2,450 RPM"


def test_legacy_recent_record_reopens_without_reintroducing_removed_choice(window, qapp):
    normalized = normalized_request(
        "Slot Cutter",
        {"cutter_diameter_mm": 25, "insert_count": 2, "operation": "Profiling", "axial_doc_mm": 2, "radial_doc_mm": 3},
    )
    result = MachiningResult(rpm=1000, feed_mm_min=200, axial_doc_mm=2, radial_doc_mm=3, confidence="medium")
    window.database.add_recent("legacy-slot-hash", normalized, result.to_dict(), "cache")
    window._load_recent()
    item = window.recent_list.item(0)
    window._load_recent_item(item)
    qapp.processEvents()

    assert window.tool_combo.currentText() == "Indexable End Mill"
    assert "Slot Cutter" not in [window.tool_combo.itemText(i) for i in range(window.tool_combo.count())]
    assert window._current_outcome is not None
    assert window._current_outcome.request_hash == "legacy-slot-hash"


def test_saved_tool_backend_data_survives_without_saved_tool_ui(window):
    window.database.save_tool("Legacy tool", "End Mill", {"diameter_mm": 12})

    assert window.database.saved_tools()[0]["name"] == "Legacy tool"
    assert not hasattr(window, "saved_tool_combo")
    assert not any(button.text() == "Save current tool" for button in window.findChildren(QPushButton))
    assert not any("Saved tool" in label.text() for label in window.findChildren(QLabel))
