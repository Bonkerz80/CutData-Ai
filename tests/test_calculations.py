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
    assert outcome.result.tap_drill_mm == pytest.approx(8.5)

