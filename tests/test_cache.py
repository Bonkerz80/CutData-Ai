import json
import sqlite3

import pytest

from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import MachiningRequest, MachineProfile, MachiningResult
from src.cutdata_ai.services.calculation_service import CalculationService
from src.cutdata_ai.services.normalization import model_cache_identity, normalize_request, request_hash
from src.cutdata_ai.services.openai_service import MockOpenAIService, ServiceResponse


MACHINE = MachineProfile("Test machine", 10000, 5000)
OTHER_MACHINE = MachineProfile("Other machine", 10000, 5000)


def req(
    diameter=22,
    *,
    material="Mild Steel",
    depth=20,
    coolant="Flood coolant",
    machine_name="Test machine",
):
    return MachiningRequest(
        machine=machine_name,
        material=material,
        tool_type="Drill",
        operation="Drilling",
        parameters={
            "diameter_mm": diameter,
            "tool_material": "HSS",
            "hole_depth_mm": depth,
            "coolant_type": coolant,
        },
    )


class CountingAI:
    is_mock = False
    def __init__(self, model="fake-model"):
        self.model = model
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


def test_model_cache_isolated_per_model_and_reusable_when_switching_back(tmp_path):
    database = Database(tmp_path / "model-cache.sqlite3")
    normalized = normalize_request(req())
    request_key = request_hash(normalized)
    luna = CountingAI("gpt-6-luna")
    sol = CountingAI("gpt-6-sol")
    astra = CountingAI("gpt-6-astra")

    luna_first = CalculationService(database, luna).calculate(req(), MACHINE)
    sol_first = CalculationService(database, sol).calculate(req(), MACHINE)
    astra_first = CalculationService(database, astra).calculate(req(), MACHINE)
    luna_again = CalculationService(database, luna).calculate(req(), MACHINE)

    assert [luna_first.request_hash, sol_first.request_hash, astra_first.request_hash] == [
        request_key, request_key, request_key
    ]
    assert luna_again.source == "cache" and luna_again.model == "gpt-6-luna"
    assert luna.calls == sol.calls == astra.calls == 1
    assert "model" not in normalized
    assert len({
        model_cache_identity(normalized, model)
        for model in ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra")
    }) == 3
    assert model_cache_identity(normalized, "gpt-6-luna", prompt_version="next-prompt") != model_cache_identity(
        normalized, "gpt-6-luna"
    )
    assert model_cache_identity(normalized, "gpt-6-luna", schema_version="next-schema") != model_cache_identity(
        normalized, "gpt-6-luna"
    )
    assert len(database.recent(10)) == 3
    assert {row["model"] for row in database.recent(10)} == {
        "gpt-6-luna", "gpt-6-sol", "gpt-6-astra"
    }
    for model in ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra"):
        identity = model_cache_identity(normalized, model)
        assert database.get_cache_record(identity, model=model)["model"] == model


def test_legacy_model_cache_is_preserved_but_not_reused_by_gpt6(tmp_path):
    database = Database(tmp_path / "legacy-model-cache.sqlite3")
    normalized = normalize_request(req())
    legacy_request_key = request_hash(normalized)
    legacy_payload = {
        "rpm": 500,
        "feed_mm_min": 50,
        "feed_per_rev_mm": 0.1,
        "coolant": "Flood coolant",
        "confidence": "medium",
        "notes": [],
        "warnings": [],
    }
    database.put_cache_record(
        legacy_request_key, normalized, legacy_payload, legacy_payload, "gpt-5.6-luna"
    )
    database.add_recent(legacy_request_key, normalized, legacy_payload, "ai", model="gpt-5.6-luna")
    ai = CountingAI("gpt-6-luna")

    outcome = CalculationService(database, ai).calculate(req(), MACHINE)

    assert outcome.source == "ai" and ai.calls == 1
    assert database.get_cache_record(legacy_request_key)["model"] == "gpt-5.6-luna"
    assert any(row["model"] == "gpt-5.6-luna" for row in database.recent(10))
    assert len(database.recent(10)) == 2


def test_legacy_recent_schema_adds_model_without_rewriting_history(tmp_path):
    path = tmp_path / "legacy-history.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE recent_calculations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_hash TEXT NOT NULL,
                normalized_request_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO recent_calculations
            (request_hash, normalized_request_json, result_json, source, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            ("old-request", "{}", "{\"rpm\": 500}", "ai", "2026-01-01T00:00:00+00:00"),
        )

    database = Database(path)
    row = database.recent(1)[0]

    assert row["request_hash"] == "old-request"
    assert row["result_json"] == '{"rpm": 500}'
    assert row["created_at"] == "2026-01-01T00:00:00+00:00"
    assert row["model"] == ""


@pytest.mark.parametrize(
    ("changed_request", "machine"),
    [
        (req(22, depth=60), MACHINE),
        (req(22, material="EN8"), MACHINE),
        (req(22, coolant="Mist"), MACHINE),
        (req(22, machine_name="Other machine"), OTHER_MACHINE),
    ],
    ids=["hole-depth", "material", "coolant", "machine"],
)
def test_materially_changed_condition_requires_a_new_ai_request(tmp_path, changed_request, machine):
    database = Database(tmp_path / "changed.sqlite3")
    ai = CountingAI()
    service = CalculationService(database, ai)

    service.calculate(req(22), MACHINE)
    outcome = service.calculate(changed_request, machine)

    assert outcome.source == "ai"
    assert outcome.cache_hit is False
    assert ai.calls == 2


def test_saved_workshop_setting_only_applies_to_exact_canonical_request(tmp_path):
    database = Database(tmp_path / "preferred-exact.sqlite3")
    ai = CountingAI()
    service = CalculationService(database, ai)
    first = service.calculate(req(22), MACHINE)
    preferred = first.result.copy()
    preferred.rpm = 650
    service.save_workshop_preference(first, preferred)

    changed = service.calculate(req(22, depth=21), MACHINE)

    assert changed.source == "ai"
    assert changed.result.rpm != 650
    assert ai.calls == 2


def test_saved_workshop_setting_is_independent_of_model(tmp_path):
    database = Database(tmp_path / "preferred-model-independent.sqlite3")
    original = CalculationService(database, CountingAI("gpt-6-luna"))
    first = original.calculate(req(22), MACHINE)
    preferred = first.result.copy()
    preferred.rpm = 650
    preferred.feed_mm_min = 65
    original.save_workshop_preference(first, preferred)

    other_model = CountingAI("gpt-6-astra")
    outcome = CalculationService(database, other_model).calculate(req(22), MACHINE)

    assert outcome.source == "workshop"
    assert outcome.result.rpm == 650
    assert outcome.request_hash == first.request_hash
    assert other_model.calls == 0


def test_mock_results_are_not_written_to_production_cache(tmp_path):
    database = Database(tmp_path / "mock.sqlite3")
    CalculationService(database, CountingAI("gpt-6-luna")).calculate(req(22), MACHINE)
    service = CalculationService(database, MockOpenAIService())
    assert service.ai_service.model == "gpt-6-luna"
    outcome = service.calculate(req(22), MACHINE)
    assert outcome.source == "mock"
    assert outcome.cache_hit is False
    assert len(database.recent(10)) == 1
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM cache_records").fetchone()[0] == 1


@pytest.mark.parametrize(("decision", "q"), [(True, 6), (False, None)])
def test_exact_cache_and_restart_preserve_ai_peck_decision(tmp_path, decision, q):
    from tests.test_calculations import FakeAI

    path = tmp_path / "peck-cache.sqlite3"
    payload = {"rpm": 800, "feed_mm_min": 80, "peck_recommended": decision, "peck_mm": q,
               "recommended_cycle": "Chosen AI drilling method"}
    ai = FakeAI(payload)
    first = CalculationService(Database(path), ai).calculate(req(), MACHINE)
    second = CalculationService(Database(path), ai).calculate(req(), MACHINE)
    assert ai.calls == 1
    assert second.source == "cache"
    assert second.result.peck_recommended is decision
    assert second.result.peck_mm == q
    assert second.result.recommended_cycle == first.result.recommended_cycle


def test_previous_drilling_prompt_cache_is_refreshed_without_deleting_history(tmp_path):
    from src.cutdata_ai.config.constants import SCHEMA_VERSION
    from tests.test_calculations import FakeAI

    database = Database(tmp_path / "old-drill-prompt.sqlite3")
    normalized = normalize_request(req())
    key = request_hash(normalized)
    old_payload = {"rpm": 800, "feed_mm_min": 80, "peck_recommended": None, "peck_mm": None}
    database.put_cache_record(key, normalized, old_payload, old_payload, "old-model", "2026-09-03.2", SCHEMA_VERSION)
    database.add_recent(key, normalized, old_payload, "ai")
    ai = FakeAI({**old_payload, "peck_recommended": False})

    refreshed = CalculationService(database, ai).calculate(req(), MACHINE)

    assert ai.calls == 1 and refreshed.source == "ai"
    assert refreshed.result.peck_recommended is False
    assert json.loads(database.recent()[1]["result_json"]) == old_payload
