import json
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QElapsedTimer, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLabel, QPushButton

from src.cutdata_ai.config.constants import TOOL_TYPES, compatible_tool_type, tool_family
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import CalculationOutcome, MachiningRequest, MachiningResult, MachineProfile
from src.cutdata_ai.services.recent_summary import build_recent_summary, recent_item_text
from src.cutdata_ai.ui.main_window import MainWindow, apply_styles


@pytest.fixture(scope="session")
def qapp():
    application = QApplication.instance() or QApplication([])
    if os.name == "nt":
        # The offscreen platform does not discover Windows fonts on its own.
        for font in ("segoeui.ttf", "segoeuib.ttf"):
            QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font}")
    apply_styles(application)
    return application


@pytest.fixture
def window(qapp, tmp_path):
    value = MainWindow(Database(tmp_path / "workflow.sqlite3"))
    value.workflow_combo.setCurrentIndex(1)
    value.details_button.setChecked(True)
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


def outcome(normalized, result, *, source="ai", model="test-model"):
    return CalculationOutcome(
        result=result,
        normalized_request=normalized,
        request_hash="exact-test-hash",
        source=source,
        cache_hit=source == "cache",
        model=model,
        validated_response=json.dumps(result.to_dict()),
    )


def test_guided_review_status_uses_warning_banner(window):
    normalized = normalized_request(
        "Indexable End Mill",
        {"diameter_mm": 25, "insert_count": 2},
        operation="AI Guided",
    )
    normalized["workflow_mode"] = "guided"
    result = MachiningResult(
        rpm=1500,
        feed_mm_min=210,
        recommended_operation="Roughing Waterline",
        recommended_strategy="Rough in axial passes",
        verification_status="review_required",
        verification_summary="The small depth change does not explain the RPM shift.",
    )

    window._show_result(outcome(normalized, result))

    assert window.result_banner.objectName() == "reviewBanner"
    assert "REVIEW REQUIRED" in window.result_banner.text()


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
    assert recent_item_text(normalized, "gpt-6-sol").endswith("GPT-6 Sol")
    assert recent_item_text(normalized, "gpt-5.6-sol").endswith("GPT-5.6 Sol")
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
    assert window.result_fields["peck_mm"].text() == "Q6 mm"
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


def test_mock_result_names_default_engine_and_stays_visibly_nonproduction(window, qapp):
    normalized = normalized_request("Drill", {"diameter_mm": 10, "hole_depth_mm": 20})
    window._show_result(
        outcome(
            normalized,
            MachiningResult(rpm=800, feed_mm_min=80),
            source="mock",
            model="gpt-6-luna",
        )
    )

    assert "DEVELOPMENT MOCK RESULT" in window.result_banner.text()
    assert "GPT-6 Luna selected" in window.result_banner.text()
    assert "not cached" in window.result_banner.text()
    assert "suitable as production data" in window.result_banner.text()


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
    window.database.add_recent("exact-drill-hash", normalized, result.to_dict(), "ai", model="gpt-6-astra")
    window._load_recent()
    qapp.processEvents()

    assert window.recent_list.count() == 1
    item = window.recent_list.item(0)
    assert "Ø22 HSS Drill · Mild Steel" in item.text()
    assert "160 mm deep · Ø8 pilot · Flood" in item.text()
    assert "GPT-6 Astra" in item.text()
    row = item.data(Qt.UserRole)
    assert row["created_at"][:16].replace("T", " ") not in item.text()

    window._load_recent_item(item)
    qapp.processEvents()

    assert window.tool_combo.currentText() == "Drill"
    assert window.pages["drill"].fields["diameter_mm"].value() == 22
    assert window._current_outcome is not None
    assert window._current_outcome.request_hash == "exact-drill-hash"
    assert window._current_outcome.model == "gpt-6-astra"
    assert window._current_outcome.source == "ai"
    assert window.result_fields["rpm"].text() == "2,450 RPM"


def test_legacy_recent_record_reopens_without_reintroducing_removed_choice(window, qapp):
    normalized = normalized_request(
        "Slot Cutter",
        {"cutter_diameter_mm": 25, "insert_count": 2, "operation": "Profiling", "axial_doc_mm": 2, "radial_doc_mm": 3},
    )
    result = MachiningResult(rpm=1000, feed_mm_min=200, axial_doc_mm=2, radial_doc_mm=3, confidence="medium")
    window.database.add_recent(
        "legacy-slot-hash", normalized, result.to_dict(), "cache", model="gpt-5.6-sol"
    )
    window._load_recent()
    item = window.recent_list.item(0)
    assert "GPT-5.6 Sol" in item.text()
    window._load_recent_item(item)
    qapp.processEvents()

    assert window.tool_combo.currentText() == "Indexable End Mill"
    assert "Slot Cutter" not in [window.tool_combo.itemText(i) for i in range(window.tool_combo.count())]
    assert window._current_outcome is not None
    assert window._current_outcome.request_hash == "legacy-slot-hash"
    assert window._current_outcome.model == "gpt-5.6-sol"
    assert window._current_outcome.source == "cache"


def test_saved_tools_and_workshop_editor_are_dormant(window, qapp):
    window.database.save_tool("Legacy tool", "End Mill", {"diameter_mm": 12})
    assert not hasattr(window, "saved_tool_combo")
    assert not hasattr(window, "workshop_button")
    texts = {button.text() for button in window.findChildren(QPushButton)}
    assert not texts.intersection({"Save current", "Remove", "Adjust / save workshop setting"})
    window._show_result(outcome(normalized_request("Drill", {}), MachiningResult(rpm=800, feed_mm_min=80)))
    assert not hasattr(window, "workshop_button")
    assert window.database.saved_tools()[0]["name"] == "Legacy tool"


@pytest.mark.parametrize(
    ("tool_type", "primary", "secondary", "derived"),
    [
        ("Drill", {"rpm", "feed_mm_min", "peck_mm"},
         {"cutting_speed", "feed_per_rev", "cycle", "coolant", "confidence"},
         {"hole_ld_ratio", "rpm_usage", "feed_usage"}),
        ("Reamer", {"rpm", "feed_mm_min", "pre_ream_size_mm"},
         {"cutting_speed", "feed_per_rev", "pre_ream_range", "cycle", "coolant", "confidence"},
         {"hole_ld_ratio", "rpm_usage", "feed_usage"}),
        ("Tap", {"rpm", "feed_mm_min", "tap_drill_mm"},
         {"cutting_speed", "feed_per_rev", "cycle", "coolant", "confidence"},
         {"rpm_usage", "feed_usage", "tap_relationship"}),
        ("End Mill", {"rpm", "feed_mm_min", "axial_doc_mm", "stepover_mm"},
         {"cutting_speed", "feed_per_tooth", "coolant", "confidence"},
         {"radial_engagement", "axial_doc_ratio", "mrr", "rpm_usage", "feed_usage"}),
        ("Indexable End Mill", {"rpm", "feed_mm_min", "axial_doc_mm", "stepover_mm"},
         {"cutting_speed", "feed_per_tooth", "coolant", "confidence"},
         {"radial_engagement", "axial_doc_ratio", "mrr", "rpm_usage", "feed_usage"}),
    ],
)
def test_startup_restores_family_with_complete_placeholder_display(
    qapp, tmp_path, tool_type, primary, secondary, derived
):
    database = Database(tmp_path / "startup.sqlite3")
    # Exercise actual startup and persisted selection, before any calculation.
    database.set_setting("last_calculator_state", json.dumps({"global": {"tool_type": tool_type, "workflow_mode": "manual", "result_details_open": True}}))
    window = MainWindow(database)
    window.show()
    qapp.processEvents()
    try:
        assert window.tool_combo.currentText() == tool_type
        assert window.result_status.text() == "Ready to calculate"
        assert window.primary_group.isVisible()
        assert window.info_group.isVisible()
        assert window.derived_group.isVisible()
        assert window.notes_group.isVisible()
        assert not window.ai_context_group.isVisible()
        assert window.notes.placeholderText() == "AI machining notes and warnings will appear here."
        for fields, expected in (
            (window.result_fields, primary),
            (window.info_labels, secondary),
            (window.derived_labels, derived),
        ):
            assert {key for key, widget in fields.items() if widget.isVisible()} == expected
            assert all(fields[key].text() == "—" for key in expected)
        assert not window.result_panel.findChildren(QDoubleSpinBox)
        assert all(field.textInteractionFlags() & Qt.TextSelectableByMouse for field in window.result_fields.values())
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_tool_selection_immediately_replaces_old_results_with_family_placeholders(window, qapp):
    fields = dict(window.result_fields)
    window.tool_combo.setCurrentText("Drill")
    assert window.result_cards["peck_mm"].isVisible()
    assert window.result_fields["peck_mm"].text() == "—"
    window._show_result(outcome(normalized_request("Drill", {}), MachiningResult(rpm=2450, feed_mm_min=365, peck_recommended=False)))

    window.tool_combo.setCurrentText("End Mill")
    qapp.processEvents()

    assert window.result_fields == fields  # Reuse the existing read-only widgets.
    assert window._current_outcome is None
    assert not window.result_cards["peck_mm"].isVisible()
    assert window.result_cards["axial_doc_mm"].isVisible()
    assert window.result_cards["stepover_mm"].isVisible()
    assert all(field.text() == "—" for field in fields.values())
    assert window.info_labels["feed_per_tooth"].isVisible()
    assert not window.info_labels["feed_per_rev"].isVisible()
    assert not window.info_labels["pre_ream_range"].isVisible()
    assert not window.derived_labels["hole_ld_ratio"].isVisible()
    assert window.derived_labels["mrr"].isVisible()
    assert not window.ai_context_group.isVisible()


@pytest.mark.parametrize(
    ("decision", "q", "text", "warning"),
    [(True, 6, "Q6 mm", False), (True, 3.5, "Q3.5 mm", False),
     (False, None, "NO PECK", False), (None, None, "NOT SPECIFIED", True),
     (None, 6, "NOT SPECIFIED", True), (True, None, "NOT SPECIFIED", True)],
)
def test_peck_card_displays_all_decisions_and_preserves_stored_data(window, qapp, decision, q, text, warning):
    result = MachiningResult(rpm=2450, feed_mm_min=365, peck_recommended=decision, peck_mm=q)
    original = result.to_dict()
    fields = dict(window.result_fields)
    window._show_result(outcome(normalized_request("Drill", {}), result))
    qapp.processEvents()

    assert window.result_fields == fields
    assert window.result_cards["peck_mm"].isVisible()
    assert window.result_fields["peck_mm"].text() == text
    assert bool(window.notes.toPlainText()) == warning
    assert result.to_dict() == original
    assert window.info_group.isVisible() and window.derived_group.isVisible()
    assert window.info_labels["cycle"].isVisible()
    assert window.info_labels["cycle"].text() == "—"
    assert window.derived_labels["hole_ld_ratio"].isVisible()
    assert window.derived_labels["hole_ld_ratio"].text() == "—"
    assert not window.ai_context_group.isVisible()


@pytest.mark.parametrize(("decision", "q", "text"), [(True, 6, "Q6 mm"), (False, None, "NO PECK"), (None, None, "NOT SPECIFIED")])
def test_recent_double_click_restores_exact_peck_decision(window, qapp, decision, q, text):
    normalized = normalized_request("Drill", {"diameter_mm": 22, "hole_depth_mm": 160})
    payload = MachiningResult(rpm=2450, feed_mm_min=365, peck_recommended=decision, peck_mm=q).to_dict()
    if decision is None:
        payload.pop("peck_recommended")  # Pre-decision legacy history.
    window.database.add_recent("exact-peck-record", normalized, payload, "ai")
    window._load_recent()
    window.tool_combo.setCurrentText("End Mill")
    qapp.processEvents()
    item = window.recent_list.item(0)
    point = window.recent_list.visualItemRect(item).center()
    QTest.mouseClick(window.recent_list.viewport(), Qt.LeftButton, pos=point)
    QTest.mouseDClick(window.recent_list.viewport(), Qt.LeftButton, pos=point)
    qapp.processEvents()

    assert window.tool_combo.currentText() == "Drill"
    assert window.result_fields["peck_mm"].isVisible()
    assert window.result_fields["peck_mm"].text() == text
    assert window._current_outcome.request_hash == "exact-peck-record"
    assert json.loads(window.database.recent()[0]["result_json"]) == payload


def test_result_population_keeps_core_group_positions_stable(window, qapp):
    apply_styles(qapp)
    qapp.processEvents()
    groups = (window.primary_group, window.info_group, window.derived_group, window.notes_group)
    before = [group.geometry() for group in groups]
    cards = {key: card.geometry() for key, card in window.result_cards.items() if card.isVisible()}
    normalized = normalized_request("Drill", {"diameter_mm": 22, "hole_depth_mm": 160})
    for decision, q in ((True, 6), (False, None), (None, None)):
        result = MachiningResult(rpm=2450, feed_mm_min=365, peck_recommended=decision, peck_mm=q,
                                 cutting_speed_m_min=169.2, feed_per_rev_mm=0.149,
                                 recommended_cycle="G83 peck cycle", coolant="Flood coolant", confidence="high")
        window._show_result(outcome(normalized, result))
        qapp.processEvents()
        assert [group.geometry() for group in groups] == before
        assert {key: window.result_cards[key].geometry() for key in cards} == cards


def test_invalid_peck_response_uses_clean_retry_and_keeps_placeholder_display(window, qapp):
    from tests.test_calculations import FakeAI

    window.ai_service = FakeAI({"rpm": 800, "feed_mm_min": 80, "peck_recommended": True, "peck_mm": None})
    window._calculate()
    assert window.primary_group.isVisible() and window.notes_group.isVisible()
    timer = QElapsedTimer()
    timer.start()
    while window._thread is not None and timer.elapsed() < 5000:
        QTest.qWait(10)

    assert window._thread is None
    assert window.retry_button.isVisible()
    assert "peck depth" in window.result_banner.text()
    assert window.result_fields["peck_mm"].text() == "—"
    assert window.result_fields["peck_mm"].isVisible()
    assert window.info_group.isVisible() and window.derived_group.isVisible()
    assert window.notes_group.isVisible()
    assert not window.database.recent()


def test_cancelled_calculation_can_be_restarted_while_old_request_winds_down(window, qapp, monkeypatch):
    gates = [threading.Event(), threading.Event()]
    started = [threading.Event(), threading.Event()]

    class ControlledCalculation:
        calls = 0

        def __init__(self, database, ai_service):
            pass

        def calculate(self, request, machine):
            index = ControlledCalculation.calls
            ControlledCalculation.calls += 1
            self.progress_callback("Researching test recommendation")
            started[index].set()
            gates[index].wait(timeout=5)
            raise RuntimeError("test request ended")

    monkeypatch.setattr("src.cutdata_ai.ui.main_window.CalculationService", ControlledCalculation)
    window._calculate()
    assert started[0].wait(timeout=2)
    QTest.qWait(30)
    assert "Researching test recommendation" in window.result_status.text()
    window._cancel_calculation()
    assert window.calculate_button.text() == "RESTART CALCULATION"
    window.calculate_button.click()
    assert "Restart queued" in window.result_status.text()
    assert ControlledCalculation.calls == 1

    gates[0].set()
    timer = QElapsedTimer()
    timer.start()
    while not started[1].is_set() and timer.elapsed() < 3000:
        QTest.qWait(10)
    assert started[1].is_set()
    assert ControlledCalculation.calls == 2
    gates[1].set()
    while window._thread is not None and timer.elapsed() < 5000:
        QTest.qWait(10)
    assert window._thread is None
    assert window.calculate_button.isEnabled()


def test_reamer_response_discards_peck_data_and_populates_debug(window, qapp):
    from tests.test_calculations import FakeAI

    window.tool_combo.setCurrentText("Reamer")
    window.ai_service = FakeAI(
        {
            "rpm": 400,
            "feed_mm_min": 40,
            "feed_per_rev_mm": 0.1,
            "peck_mm": 2,
            "peck_recommended": True,
            "recommended_cycle": "G83 peck cycle",
        }
    )
    window._calculate()
    timer = QElapsedTimer()
    timer.start()
    while window._thread is not None and timer.elapsed() < 5000:
        QTest.qWait(10)

    assert window._thread is None
    assert not window.result_banner.text().startswith("Could not calculate")
    assert window.debug_group.isVisible()
    assert window.debug_button.isChecked()
    assert '"tool_type": "reamer"' in window.debug_editors["normalized"].toPlainText()
    assert window.debug_editors["prompt"].toPlainText() == "test prompt"
    assert "G83 peck cycle" in window.debug_editors["raw"].toPlainText()
    assert '"recommended_cycle": null' in window.debug_editors["validated"].toPlainText()
    assert "continuous-feed reaming" in window.notes.toPlainText()


def test_details_are_collapsed_by_default_and_key_warnings_are_limited(qapp, tmp_path):
    window = MainWindow(Database(tmp_path / "details.sqlite3"))
    window.show()
    qapp.processEvents()
    try:
        assert not window.details_button.isChecked()
        assert window.primary_group.isVisible()
        assert not window.info_group.isVisible()
        assert not window.notes_group.isVisible()
        # A Guided profile job never shows drilling placeholders.
        assert not window.result_cards["peck_mm"].isVisible()
        assert window.result_cards["axial_doc_mm"].isVisible()

        result = MachiningResult(
            rpm=1000, feed_mm_min=200, feed_per_tooth_mm=0.1, axial_doc_mm=2, radial_doc_mm=3,
            warnings=[
                "Check clamp clearance.",
                "RPM limited locally to the Generic CNC Mill maximum of 12000 RPM.",
                "Verify chip evacuation.",
                "Independent check requires operator review: speed is high.",
                "Confirm stickout.",
            ],
        )
        window._show_result(outcome(normalized_request("End Mill", {"diameter_mm": 10, "flute_count": 2}, operation="Roughing Waterline"), result))
        qapp.processEvents()
        lines = window.key_warnings.text().splitlines()
        assert window.key_warnings.isVisible()
        assert "Independent check requires operator review" in lines[0]
        assert "limited locally" in lines[1]
        assert lines[-1] == "+ 2 more under Details"
        assert "Confirm stickout." in window.notes.toPlainText()

        window.details_button.setChecked(True)
        qapp.processEvents()
        assert window.info_group.isVisible() and window.notes_group.isVisible()
        assert not window.key_warnings.isVisible()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
