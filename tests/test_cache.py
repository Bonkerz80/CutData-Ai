import json

from src.cutdata_ai.config.constants import PROMPT_VERSION, SCHEMA_VERSION
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import MachiningRequest, MachineProfile, MachiningResult
from src.cutdata_ai.services.calculation_service import CalculationService
from src.cutdata_ai.services.normalization import normalize_request, request_hash
from src.cutdata_ai.services.openai_service import MockOpenAIService, ServiceResponse


MACHINE = MachineProfile("Test machine", 10000, 5000)


def req(diameter):
    return MachiningRequest(
        machine="Test machine",
        material="Mild Steel",
        tool_type="Drill",
        operation="Drilling",
        parameters={"diameter_mm": diameter, "tool_material": "HSS", "hole_depth_mm": 20},
    )


class CountingAI:
    is_mock = False
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def calculate(self, request, machine):
        self.calls += 1
        payload = {"rpm": 800, "feed_mm_min": 80, "feed_per_rev_mm": 0.1, "coolant": "Flood coolant", "confidence": "high", "notes": [], "warnings": []}
        return ServiceResponse(payload, json.dumps(payload), "prompt", self.model)


def test_numeric_normalization_uses_one_hash_for_22_variants():
    assert normalize_request(req(22)) == normalize_request(req(22.0))
    assert request_hash(normalize_request(req(22))) == request_hash(normalize_request(req(22.00)))


def test_cache_exact_match_avoids_second_api_call(tmp_path):
    database = Database(tmp_path / "cache.sqlite3")
    ai = CountingAI()
    service = CalculationService(database, ai)
    first = service.calculate(req(22), MACHINE)
    second = service.calculate(req(22.0), MACHINE)
    assert first.source == "ai"
    assert second.source == "cache"
    assert second.cache_hit is True
    assert ai.calls == 1


def test_cache_survives_database_restart(tmp_path):
    path = tmp_path / "restart.sqlite3"
    ai = CountingAI()
    CalculationService(Database(path), ai).calculate(req(22), MACHINE)
    restarted = CalculationService(Database(path), ai)
    outcome = restarted.calculate(req(22.00), MACHINE)
    assert outcome.source == "cache"
    assert ai.calls == 1


def test_prompt_and_schema_version_invalidate_old_cache(tmp_path):
    path = tmp_path / "version.sqlite3"
    database = Database(path)
    normalized = normalize_request(req(22))
    key = request_hash(normalized)
    payload = {"rpm": 800, "feed_mm_min": 80, "feed_per_rev_mm": 0.1, "coolant": "Flood coolant", "confidence": "high", "notes": [], "warnings": []}
    database.put_cache_record(key, normalized, payload, payload, "old-model", "old-prompt", "old-schema")
    ai = CountingAI()
    outcome = CalculationService(database, ai).calculate(req(22), MACHINE)
    assert outcome.source == "ai"
    assert ai.calls == 1


def test_saved_workshop_setting_takes_priority(tmp_path):
    database = Database(tmp_path / "preferred.sqlite3")
    ai = CountingAI()
    service = CalculationService(database, ai)
    first = service.calculate(req(22), MACHINE)
    preferred = first.result.copy()
    preferred.rpm = 650
    preferred.feed_mm_min = 65
    service.save_workshop_preference(first, preferred)
    second = service.calculate(req(22), MACHINE)
    assert second.source == "workshop"
    assert second.result.rpm == 650
    assert second.result.feed_mm_min == 65
    assert ai.calls == 1


def test_mock_results_are_not_written_to_production_cache(tmp_path):
    database = Database(tmp_path / "mock.sqlite3")
    service = CalculationService(database, MockOpenAIService())
    outcome = service.calculate(req(22), MACHINE)
    assert outcome.source == "mock"
    assert database.get_cache_record(outcome.request_hash) is None

