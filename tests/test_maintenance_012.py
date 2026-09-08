import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.cutdata_ai.config.constants import COATINGS, PROMPT_VERSION
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import MachiningRequest
from src.cutdata_ai.services.normalization import normalize_request, request_hash
from src.cutdata_ai.services.openai_service import MockOpenAIService
from src.cutdata_ai.ui.widgets import DrillPage, EndMillPage


def test_fresh_machine_profiles_use_correct_vf2_and_vf9_limits(tmp_path):
    profiles = {item["name"]: item for item in Database(tmp_path / "fresh.sqlite3").machine_profiles()}

    assert profiles["HAAS VF-2"]["max_rpm"] == 8000
    assert profiles["HAAS VF-9"]["max_rpm"] == 10000


def test_machine_migration_changes_only_exact_old_vf2_value(tmp_path):
    database_path = tmp_path / "migration.sqlite3"
    database = Database(database_path)
    vf2 = next(item for item in database.machine_profiles() if item["name"] == "HAAS VF-2")
    database.update_machine_profile("HAAS VF-2", {**vf2, "max_rpm": 12000})
    database.update_machine_profile("HAAS VF-9", {**next(item for item in database.machine_profiles() if item["name"] == "HAAS VF-9"), "max_rpm": 9000})
    Database(database_path)
    profiles = {item["name"]: item for item in Database(database_path).machine_profiles()}

    assert profiles["HAAS VF-2"]["max_rpm"] == 8000
    assert profiles["HAAS VF-9"]["max_rpm"] == 9000


def test_machine_migration_preserves_custom_vf2_row(tmp_path):
    database_path = tmp_path / "custom-vf2.sqlite3"
    database = Database(database_path)
    vf2 = next(item for item in database.machine_profiles() if item["name"] == "HAAS VF-2")
    database.update_machine_profile(
        "HAAS VF-2",
        {**vf2, "max_rpm": 12000, "max_feed_mm_min": 9000},
    )

    migrated = {item["name"]: item for item in Database(database_path).machine_profiles()}

    assert migrated["HAAS VF-2"]["max_rpm"] == 12000
    assert migrated["HAAS VF-2"]["max_feed_mm_min"] == 9000


def test_corrected_machine_limit_reaches_deterministic_result():
    request = MachiningRequest(
        "HAAS VF-2",
        "Mild Steel",
        "Drill",
        "Drilling",
        {"diameter_mm": 2},
    )
    result = MockOpenAIService().calculate(request, type("Machine", (), {
        "name": "HAAS VF-2",
        "max_rpm": 8000,
        "max_feed_mm_min": 10000,
        "spindle_power_kw": None,
        "coolant_capability": "Flood coolant",
        "rigidity": "medium-high",
    })())

    assert result.payload["rpm"] <= 8000


def test_central_coatings_and_legacy_other_state_are_supported(qapp=None):
    app = QApplication.instance() or QApplication([])
    expected = (
        "Uncoated", "TiN", "TiCN", "TiAlN", "AlTiN", "Cupro (ITC)",
        "AlCrN", "ZrN", "DLC", "CVD Diamond", "Other / Proprietary",
    )
    assert COATINGS == expected
    for page_type in (DrillPage, EndMillPage):
        page = page_type()
        assert [page.fields["coating"].itemText(i) for i in range(page.fields["coating"].count())] == list(expected)
        page.load_values({"coating": "Other"})
        assert page.values()["coating"] == "Other / Proprietary"
        page.deleteLater()
    app.processEvents()


def test_coating_is_part_of_exact_request_identity_and_prompt_version():
    first = MachiningRequest("Generic CNC Mill", "Mild Steel", "Drill", "Drilling", {"diameter_mm": 10, "coating": "TiAlN"})
    second = MachiningRequest("Generic CNC Mill", "Mild Steel", "Drill", "Drilling", {"diameter_mm": 10, "coating": "Cupro (ITC)"})

    assert request_hash(normalize_request(first)) != request_hash(normalize_request(second))
    assert PROMPT_VERSION == "2026-09-07.3"
