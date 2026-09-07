"""Regression coverage for the streamlined ENCY calculator contract."""
import json
import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.cutdata_ai.config.constants import tool_family
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import MachiningRequest, MachiningResult, MachineProfile, CalculationOutcome
from src.cutdata_ai.models.schema import StructuredResponseError
from src.cutdata_ai.services.calculation_service import CalculationService, CalculationInputError, validate_and_correct_result
from src.cutdata_ai.services.normalization import normalize_request, request_hash
from src.cutdata_ai.ui.main_window import MainWindow
from tests.test_cache import CountingAI


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Database(tmp_path / "correction.sqlite3"))
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("tool,operation,hidden,active", [
    ("End Mill", "Finishing Plane", "axial_doc_mm", "radial_doc_mm"),
    ("Ball Nose End Mill", "Finishing Waterline", "radial_doc_mm", "axial_doc_mm"),
    ("End Mill", "Roughing Waterline", "ball_nose_contact", "radial_doc_mm"),
    ("Ball Nose End Mill", "Finishing Plane", "corner_radius_mm", "ball_nose_contact"),
    ("Bull Nose / Corner Radius End Mill", "Finishing Plane", "ball_nose_contact", "corner_radius_mm"),
])
def test_full_state_and_active_request_have_separate_identities(window, tool, operation, hidden, active):
    # Window is deliberately never shown: applicability must not depend on ancestors.
    window.tool_combo.setCurrentText(tool)
    page = window.pages[tool_family(tool)]
    page.load_values({"operation": operation, "corner_radius_mm": 1})
    original = window._collect_request()
    normalized = normalize_request(original)
    assert hidden not in original.parameters
    assert active in original.parameters
    before = page.values()[hidden]
    changed = 20 if isinstance(before, (int, float)) else "Full-radius contact"
    page.load_values({hidden: changed})
    assert page.values()[hidden] == changed
    window._save_calculator_state()
    saved = json.loads(window.database.get_setting("last_calculator_state"))
    assert saved["families"][tool_family(tool)][hidden] == changed
    assert normalize_request(window._collect_request()) == normalized
    assert request_hash(normalize_request(window._collect_request())) == request_hash(normalized)
    current = page.values()[active]
    page.load_values({active: 2 if isinstance(current, (int, float)) else "Angled / ramp contact"})
    assert request_hash(normalize_request(window._collect_request())) != request_hash(normalized)
    # Service-level canonicalisation also ignores stale fields from non-UI callers.
    dirty = replace(original, parameters={**original.parameters, hidden: changed})
    assert normalize_request(dirty) == normalized


def test_optional_zero_and_false_semantics(window):
    window.tool_combo.setCurrentText("Drill")
    request = window._collect_request()
    assert "existing_pilot_hole_diameter_mm" not in request.parameters
    assert request.parameters["internal_coolant"] is False
    window.tool_combo.setCurrentText("Tap")
    window.pages["tap"].load_values({"rigid_tapping": False})
    assert window._collect_request().parameters["rigid_tapping"] is False


def test_thread_mill_cannot_bypass_legacy_operation_guard(window):
    window.tool_combo.setCurrentText("Thread Mill")
    ai = CountingAI()
    with pytest.raises(CalculationInputError, match="legacy operation"):
        CalculationService(window.database, ai).calculate(window._collect_request(), window._machine())
    assert ai.calls == 0


def test_material_context_is_independent_of_window_visibility(window):
    window.material_combo.setCurrentText("Toolox 44")
    window.hardness.setValue(44)
    assert window._collect_request().hardness_hrc == 44
    window.material_combo.setCurrentText("Mild Steel")
    assert window._collect_request().hardness_hrc is None
    window.material_combo.setCurrentText("Custom / Other")
    window.custom_material.setText("Custom alloy")
    assert window._collect_request().custom_material == "Custom alloy"


@pytest.mark.parametrize("operation,titles,lateral,mrr", [
    ("Roughing Waterline", ["SPINDLE", "FEED", "DEPTH STEP", "RADIAL ENGAGEMENT"], 2, "0.600"),
    ("Face Milling", ["SPINDLE", "FEED", "DEPTH OF CUT", "WIDTH OF CUT"], 2, "0.600"),
    ("Finishing Waterline", ["SPINDLE", "FEED", "Z STEP"], None, None),
    ("Finishing Plane", ["SPINDLE", "FEED", "STEPOVER"], 1, None),
    ("Flat Land Finishing", ["SPINDLE", "FEED", "STEPOVER"], 1, None),
])
def test_operation_placeholders_results_and_derived(window, operation, titles, lateral, mrr):
    window.tool_combo.setCurrentText("End Mill")
    window.pages["end_mill"].load_values({"operation": operation})
    def shown_titles():
        return [window.result_titles[key].text() for key, card in window.result_cards.items() if not card.isHidden()]
    assert shown_titles() == titles
    assert all(window.result_fields[k].text() == "—" for k, c in window.result_cards.items() if not c.isHidden())
    result = MachiningResult(rpm=1000, feed_mm_min=100, axial_doc_mm=3, radial_doc_mm=2, stepover_mm=1)
    normalized = normalize_request(window._collect_request())
    outcome = CalculationOutcome(result=result, normalized_request=normalized, request_hash="test",
                                 source="cache", cache_hit=True, model="fake")
    window._show_result(outcome)
    assert shown_titles() == titles
    assert window.result_fields["rpm"].text() != "—"
    if lateral is not None:
        assert window.result_fields["stepover_mm"].text() == f"{lateral:g} mm"
        assert f"{lateral * 10:.1f}% cutter D" in window.derived_labels["radial_engagement"].text()
    if mrr:
        assert window.derived_labels["mrr"].text() == f"{mrr} cm³/min"
    else:
        assert window.derived_labels["mrr"].text() == "—"
        assert window.derived_rows["mrr"][0].isHidden()
    assert "%" in window.derived_labels["rpm_usage"].text()
    assert "%" in window.derived_labels["feed_usage"].text()


def test_legacy_history_viewable_but_new_request_blocked(window):
    normalized = normalize_request(MachiningRequest(machine="Generic CNC Mill", material="Mild Steel",
        tool_type="End Mill", operation="Profiling", parameters={"diameter_mm": 10, "flute_count": 2}))
    result = MachiningResult(rpm=800, feed_mm_min=80)
    window.database.put_cache_record("legacy-test", normalized, result.to_dict(), result.to_dict(), "fake")
    window.database.add_recent("legacy-test", normalized, result.to_dict(), "ai")
    window._load_recent()
    item = next(window.recent_list.item(i) for i in range(window.recent_list.count())
                if "Profiling" in window.recent_list.item(i).text())
    window._load_recent_item(item)
    assert window.pages["end_mill"].values()["operation"].casefold() == "profiling"
    assert window._current_outcome.result.rpm == 800
    ai = CountingAI()
    window.ai_service = ai
    window._calculate()
    assert window._thread is None
    assert "legacy operation" in window.result_banner.text()
    assert ai.calls == 0
    service = CalculationService(window.database, ai)
    with pytest.raises(CalculationInputError, match="legacy operation"):
        service.calculate(window._collect_request(), window._machine())
    window.pages["end_mill"].load_values({"operation": "Roughing Waterline"})
    service.calculate(window._collect_request(), window._machine())
    assert ai.calls == 1


@pytest.mark.parametrize("decision,q,valid", [
    (True, 6, True), (True, None, False), (True, 0, False),
    (False, None, True), (False, 6, False),
])
def test_drill_q_consistency(decision, q, valid):
    request = MachiningRequest(machine="test", material="Mild Steel", tool_type="Drill",
                                operation="Drilling", parameters={"diameter_mm": 10})
    result = MachiningResult(rpm=800, feed_mm_min=80, peck_recommended=decision, peck_mm=q)
    machine = MachineProfile("test", 10000, 5000)
    if valid:
        validated, _ = validate_and_correct_result(result, request, machine)
        assert validated.peck_mm == q
    else:
        with pytest.raises(StructuredResponseError):
            validate_and_correct_result(result, request, machine)


def test_old_conflicting_peck_history_remains_readable(window):
    window.tool_combo.setCurrentText("Drill")
    result = MachiningResult(rpm=800, feed_mm_min=80, peck_recommended=False, peck_mm=6)
    normalized = normalize_request(window._collect_request())
    window.database.add_recent("old", normalized, result.to_dict(), "ai")
    window._load_recent()
    window._load_recent_item(window.recent_list.item(0))
    assert window.result_fields["peck_mm"].text() == "PECK DATA CONFLICT"
    assert "Stored result says no peck but also contains a Q value" in window.notes.toPlainText()
    assert result.peck_mm == 6


def test_service_filters_before_ai_and_reuses_exact_cache(window):
    window.tool_combo.setCurrentText("End Mill")
    window.pages["end_mill"].load_values({"operation": "Finishing Plane"})
    request = window._collect_request()

    class InspectAI(CountingAI):
        def calculate(self, request, machine):
            assert "axial_doc_mm" not in request.parameters
            assert "ball_nose_contact" not in request.parameters
            return super().calculate(request, machine)

    ai = InspectAI()
    service = CalculationService(window.database, ai)
    dirty = replace(request, parameters={**request.parameters, "axial_doc_mm": 3, "ball_nose_contact": "old"})
    first = service.calculate(dirty, window._machine())
    dirty.parameters["axial_doc_mm"] = 20
    second = service.calculate(dirty, window._machine())
    assert first.request_hash == second.request_hash
    assert second.source == "cache"
    assert ai.calls == 1
    dirty.parameters["radial_doc_mm"] = 2
    assert service.calculate(dirty, window._machine()).request_hash != first.request_hash
    assert ai.calls == 2
