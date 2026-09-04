import json

import pytest

from src.cutdata_ai.models.domain import MachiningRequest, MachineProfile, MachiningResult
from src.cutdata_ai.models.schema import StructuredResponseError
from src.cutdata_ai.services.calculation_service import (
    CalculationService,
    cutting_speed_m_min,
    drilling_feed_mm_min,
    milling_feed_mm_min,
    tapping_feed_mm_min,
    validate_and_correct_result,
)
from src.cutdata_ai.services.openai_service import ServiceResponse


MACHINE = MachineProfile("Test machine", max_rpm=1000, max_feed_mm_min=2000, rigidity="medium")


def request(tool_type="Drill", parameters=None):
    return MachiningRequest(
        machine=MACHINE.name,
        material="Mild Steel",
        tool_type=tool_type,
        operation="Drilling" if tool_type == "Drill" else "Profiling",
        parameters=parameters or {"diameter_mm": 10.0, "tool_material": "HSS", "hole_depth_mm": 20.0},
    )


class FakeAI:
    is_mock = False
    model = "fake-model"

    def __init__(self, payload=None):
        self.calls = 0
        self.payload = payload or {
            "rpm": 800,
            "feed_mm_min": 80,
            "feed_per_rev_mm": 0.1,
            "coolant": "Flood coolant",
            "confidence": "medium",
            "notes": ["Use as a starting point."],
            "warnings": [],
        }

    def calculate(self, req, machine):
        self.calls += 1
        return ServiceResponse(
            payload=self.payload,
            raw_text=json.dumps(self.payload),
            prompt="test prompt",
            model=self.model,
            response_id="test-response",
            usage={"input_tokens": 10, "output_tokens": 5},
        )


def test_cutting_speed_calculation():
    assert cutting_speed_m_min(10, 1000) == pytest.approx(31.4159, rel=1e-5)


def test_milling_feed_calculation():
    assert milling_feed_mm_min(2000, 3, 0.05) == pytest.approx(300)


def test_drilling_feed_calculation():
    assert drilling_feed_mm_min(1500, 0.12) == pytest.approx(180)


def test_tapping_feed_calculation():
    assert tapping_feed_mm_min(1200, 1.5) == pytest.approx(1800)


def test_machine_maximum_rpm_is_enforced(tmp_path):
    payload = {"rpm": 5000, "feed_mm_min": 500, "feed_per_rev_mm": 0.1, "coolant": "Flood coolant", "confidence": "high", "notes": [], "warnings": []}
    ai = FakeAI(payload)
    from src.cutdata_ai.database.database import Database

    outcome = CalculationService(Database(tmp_path / "limits.sqlite3"), ai).calculate(request(), MACHINE)
    assert outcome.result.rpm == 1000
    assert outcome.result.feed_mm_min == pytest.approx(100)
    assert outcome.result.cutting_speed_m_min == pytest.approx(cutting_speed_m_min(10, 1000))
    assert outcome.validation_corrections


def test_malformed_incomplete_api_response_is_rejected(tmp_path):
    ai = FakeAI({"feed_mm_min": 100, "notes": [], "warnings": []})
    from src.cutdata_ai.database.database import Database

    with pytest.raises(StructuredResponseError):
        CalculationService(Database(tmp_path / "bad.sqlite3"), ai).calculate(request(), MACHINE)


def test_rigid_tap_feed_is_recalculated_locally(tmp_path):
    payload = {"rpm": 600, "feed_mm_min": 12, "feed_per_rev_mm": 0.02, "coolant": "Tapping oil", "confidence": "medium", "notes": [], "warnings": []}
    req = request("Tap", {"diameter_mm": 10, "pitch_mm": 1.5, "thread_size": "M10", "tool_material": "HSS"})
    from src.cutdata_ai.database.database import Database

    outcome = CalculationService(Database(tmp_path / "tap.sqlite3"), FakeAI(payload)).calculate(req, MACHINE)
    assert outcome.result.tap_pitch_mm == pytest.approx(1.5)
    assert outcome.result.feed_mm_min == pytest.approx(900)
    assert outcome.result.feed_per_rev_mm == pytest.approx(1.5)
    assert outcome.result.tap_drill_mm is None


def test_milling_feed_is_corrected_from_ai_feed_per_tooth():
    req = request("End Mill", {"diameter_mm": 10, "flute_count": 4, "tool_material": "Carbide", "operation": "Profiling"})
    result = MachiningResult(rpm=2000, feed_mm_min=250, feed_per_tooth_mm=0.04)
    machine = MachineProfile("Milling machine", max_rpm=5000, max_feed_mm_min=2000, rigidity="medium")

    corrected, corrections = validate_and_correct_result(result, req, machine)

    assert corrected.feed_mm_min == pytest.approx(320)
    assert corrected.feed_per_tooth_mm == pytest.approx(0.04)
    assert any("Milling feed recalculated" in item for item in corrections)


def test_drilling_feed_is_corrected_from_ai_feed_per_rev():
    req = request("Drill", {"diameter_mm": 10, "tool_material": "HSS", "hole_depth_mm": 20})
    result = MachiningResult(rpm=400, feed_mm_min=70, feed_per_rev_mm=0.2)

    corrected, corrections = validate_and_correct_result(result, req, MACHINE)

    assert corrected.feed_mm_min == pytest.approx(80)
    assert corrected.feed_per_rev_mm == pytest.approx(0.2)
    assert any("Feed recalculated" in item for item in corrections)


def test_rigid_tapping_preserves_exact_pitch_relationship():
    req = request(
        "Tap",
        {"diameter_mm": 10, "pitch_mm": 1.5, "thread_size": "M10", "tap_type": "Cutting tap", "rigid_tapping": True},
    )
    result = MachiningResult(rpm=600, feed_mm_min=12, feed_per_rev_mm=0.02)

    corrected, _ = validate_and_correct_result(result, req, MACHINE)

    assert corrected.tap_pitch_mm == pytest.approx(1.5)
    assert corrected.feed_per_rev_mm == pytest.approx(1.5)
    assert corrected.feed_mm_min == pytest.approx(900)


def test_rigid_tapping_feed_limit_reduces_rpm_without_changing_pitch():
    machine = MachineProfile("Limited tap machine", max_rpm=5000, max_feed_mm_min=900, rigidity="medium")
    req = request(
        "Tap",
        {"diameter_mm": 10, "pitch_mm": 1.5, "thread_size": "M10", "rigid_tapping": True},
    )
    result = MachiningResult(rpm=1000, feed_mm_min=1500, feed_per_rev_mm=1.5)

    corrected, corrections = validate_and_correct_result(result, req, machine)

    assert corrected.rpm == pytest.approx(600)
    assert corrected.feed_mm_min == pytest.approx(900)
    assert corrected.tap_pitch_mm == pytest.approx(1.5)
    assert corrected.feed_per_rev_mm == pytest.approx(1.5)
    assert any("preserving RPM × exact pitch" in item for item in corrections)


@pytest.mark.parametrize(
    ("tool_type", "parameters", "result", "expected_rpm"),
    [
        (
            "Drill",
            {"diameter_mm": 10, "tool_material": "HSS", "hole_depth_mm": 20},
            MachiningResult(rpm=1000, feed_mm_min=200, feed_per_rev_mm=0.2),
            500,
        ),
        (
            "End Mill",
            {"diameter_mm": 10, "flute_count": 4, "tool_material": "Carbide", "operation": "Profiling"},
            MachiningResult(rpm=1000, feed_mm_min=400, feed_per_tooth_mm=0.1),
            250,
        ),
    ],
    ids=["drilling", "milling"],
)
def test_machine_feed_limit_reduces_rpm_and_preserves_dependent_feed(tool_type, parameters, result, expected_rpm):
    machine = MachineProfile("Feed-limited machine", max_rpm=5000, max_feed_mm_min=100, rigidity="medium")

    corrected, _ = validate_and_correct_result(result, request(tool_type, parameters), machine)

    assert corrected.rpm == pytest.approx(expected_rpm)
    assert corrected.feed_mm_min == pytest.approx(100)
    if tool_type == "Drill":
        assert corrected.feed_per_rev_mm == pytest.approx(0.2)
    else:
        assert corrected.feed_per_tooth_mm == pytest.approx(0.1)


def test_deep_hole_without_ai_peck_does_not_receive_a_local_q_value():
    req = request("Drill", {"diameter_mm": 10, "tool_material": "HSS", "hole_depth_mm": 100})
    result = MachiningResult(rpm=500, feed_mm_min=50, feed_per_rev_mm=0.1)

    corrected, corrections = validate_and_correct_result(result, req, MACHINE)

    assert corrected.peck_recommended is None
    assert corrected.peck_mm is None
    assert all("peck" not in item.casefold() for item in corrections)


def test_deep_hole_valid_no_peck_recommendation_is_not_overridden():
    req = request("Drill", {"diameter_mm": 10, "tool_material": "HSS", "hole_depth_mm": 100})
    result = MachiningResult(rpm=500, feed_mm_min=50, feed_per_rev_mm=0.1, peck_recommended=False)

    corrected, _ = validate_and_correct_result(result, req, MACHINE)

    assert corrected.peck_recommended is False
    assert corrected.peck_mm is None


def test_ai_peck_without_q_is_rejected_instead_of_inventing_q():
    req = request("Drill", {"diameter_mm": 10, "tool_material": "HSS", "hole_depth_mm": 100})
    result = MachiningResult(rpm=500, feed_mm_min=50, feed_per_rev_mm=0.1, peck_recommended=True)

    with pytest.raises(StructuredResponseError, match="peck depth"):
        validate_and_correct_result(result, req, MACHINE)


def test_omitted_metric_tap_drill_is_not_derived_locally():
    req = request("Tap", {"diameter_mm": 10, "pitch_mm": 1.5, "thread_size": "M10", "rigid_tapping": True})
    result = MachiningResult(rpm=600, feed_mm_min=900, feed_per_rev_mm=1.5, tap_drill_mm=None)

    corrected, _ = validate_and_correct_result(result, req, MACHINE)

    assert corrected.tap_drill_mm is None


def test_form_tap_does_not_receive_cutting_tap_drill_formula():
    req = request(
        "Tap",
        {"diameter_mm": 10, "pitch_mm": 1.5, "thread_size": "M10", "tap_type": "Form tap", "rigid_tapping": True},
    )
    result = MachiningResult(rpm=600, feed_mm_min=900, feed_per_rev_mm=1.5, tap_drill_mm=None)

    corrected, _ = validate_and_correct_result(result, req, MACHINE)

    assert corrected.tap_drill_mm is None


def test_omitted_reaming_allowance_is_not_manufactured_locally():
    req = request("Reamer", {"diameter_mm": 10, "existing_hole_diameter_mm": 9.8, "hole_depth_mm": 20})
    result = MachiningResult(rpm=400, feed_mm_min=40, feed_per_rev_mm=0.1)

    corrected, _ = validate_and_correct_result(result, req, MACHINE)

    assert corrected.pre_ream_size_mm is None
    assert corrected.reaming_stock_mm is None


def test_invalid_reamer_peck_cycle_is_rejected_without_rewriting_ai_data():
    req = request("Reamer", {"diameter_mm": 10, "existing_hole_diameter_mm": 9.8, "hole_depth_mm": 20})
    result = MachiningResult(
        rpm=400,
        feed_mm_min=40,
        feed_per_rev_mm=0.1,
        recommended_cycle="G83 peck cycle",
    )

    with pytest.raises(StructuredResponseError, match="drilling-style peck"):
        validate_and_correct_result(result, req, MACHINE)


def test_invalid_peck_type_is_rejected_cleanly(tmp_path):
    payload = {
        "rpm": 800,
        "feed_mm_min": 80,
        "feed_per_rev_mm": 0.1,
        "peck_recommended": "yes",
        "coolant": "Flood coolant",
        "confidence": "medium",
        "notes": [],
        "warnings": [],
    }
    from src.cutdata_ai.database.database import Database

    with pytest.raises(StructuredResponseError, match="peck_recommended"):
        CalculationService(Database(tmp_path / "invalid-peck.sqlite3"), FakeAI(payload)).calculate(request(), MACHINE)
