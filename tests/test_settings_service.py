import pytest

from src.cutdata_ai.config.settings import AppSettings
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.services.settings_service import (
    API_KEY_SOURCE_ENVIRONMENT,
    API_KEY_SOURCE_NONE,
    API_KEY_SOURCE_SAVED,
    SecretStore,
    SettingsService,
)


def fake_secret_store(monkeypatch):
    monkeypatch.setattr(SecretStore, "protect", staticmethod(lambda value: f"dpapi:{value}"))
    monkeypatch.setattr(
        SecretStore,
        "unprotect",
        staticmethod(lambda value: value.removeprefix("dpapi:") if value.startswith("dpapi:") else ""),
    )


def test_different_environment_and_saved_keys_select_saved_source(tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    database = Database(tmp_path / "settings.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")

    status = service.get_api_key_status()
    assert service.get_api_key() == "saved-secret"
    assert service.get_api_key_source() == API_KEY_SOURCE_SAVED
    assert status.saved_configured is True
    assert status.environment_detected is True
    assert status.keys_match is False


def test_matching_environment_and_saved_keys_keep_environment_source(tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "same-secret")
    database = Database(tmp_path / "matching.sqlite3")
    service = SettingsService(database)
    service.save_api_key("same-secret")
    database.set_setting("api_key_source", "")

    status = service.get_api_key_status()
    assert service.get_api_key() == "same-secret"
    assert service.get_api_key_source() == API_KEY_SOURCE_ENVIRONMENT
    assert status.keys_match is True


def test_explicit_environment_source_is_authoritative_when_saved_key_differs(tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    database = Database(tmp_path / "explicit-source.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")
    service.set_api_key_source(API_KEY_SOURCE_ENVIRONMENT)

    assert service.get_api_key() == "environment-secret"
    assert service.get_api_key_source() == API_KEY_SOURCE_ENVIRONMENT
    assert service.load().api_key_source == API_KEY_SOURCE_ENVIRONMENT


def test_explicit_missing_source_does_not_silently_fallback(tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    database = Database(tmp_path / "no-fallback.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")
    service.set_api_key_source(API_KEY_SOURCE_SAVED)
    service.clear_saved_api_key()

    assert service.get_api_key() == "environment-secret"
    assert service.get_api_key_source() == API_KEY_SOURCE_ENVIRONMENT


def test_saved_key_is_detected_without_environment_key(tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "saved.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")

    assert service.get_api_key() == "saved-secret"
    assert service.get_api_key_source() == API_KEY_SOURCE_SAVED
    assert service.get_api_key_status().saved_configured is True
    assert service.get_api_key_status().environment_detected is False


def test_no_key_returns_none_source(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = SettingsService(Database(tmp_path / "none.sqlite3"))

    assert service.get_api_key() == ""
    assert service.get_api_key_source() == API_KEY_SOURCE_NONE
    assert service.get_api_key_status().source == API_KEY_SOURCE_NONE
    assert service.get_api_key_status().keys_match is None


def test_saved_key_prevents_mock_default_from_returning_after_restart(tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "restart.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")

    assert SettingsService(database).load().mock_mode is False
    assert SettingsService(database).load().mock_mode is False


def test_mock_and_live_mode_persist_as_explicit_choices(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = SettingsService(Database(tmp_path / "mode.sqlite3"))

    service.save(AppSettings(mock_mode=True))
    assert service.load().mock_mode is True
    service.save(AppSettings(mock_mode=False))
    assert service.load().mock_mode is False


def test_appearance_defaults_to_light_and_persists_dark_choice(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = SettingsService(Database(tmp_path / "appearance.sqlite3"))

    assert service.load().appearance == "light"
    service.save(AppSettings(appearance="dark"))
    assert service.load().appearance == "dark"
    service.save(AppSettings(appearance="invalid"))
    assert service.load().appearance == "light"


def test_clear_saved_key_does_not_remove_environment_key(tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    database = Database(tmp_path / "clear.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")

    service.clear_saved_api_key()

    assert database.get_setting("openai_api_key") == ""
    assert service.get_saved_api_key() == ""
    assert service.get_api_key() == "environment-secret"
    assert service.get_api_key_source() == API_KEY_SOURCE_ENVIRONMENT


def test_json_settings_round_trip_and_malformed_fallback(tmp_path):
    service = SettingsService(Database(tmp_path / "json.sqlite3"))
    payload = {"families": {"drill": {"diameter_mm": 8.5}}, "maximized": False}

    service.save_json_setting("last_calculator_state", payload)

    assert service.load_json_setting("last_calculator_state") == payload
    service.database.set_setting("last_calculator_state", "{not-json")
    assert service.load_json_setting("last_calculator_state", {"safe": True}) == {"safe": True}


@pytest.mark.parametrize(
    ("legacy_model", "expected_model"),
    [
        ("gpt-5.6-luna", "gpt-6-luna"),
        ("gpt-5.6-terra", "gpt-6-sol"),
        ("gpt-5.6-sol", "gpt-6-astra"),
    ],
)
def test_saved_model_preferences_migrate_by_capability_tier(tmp_path, legacy_model, expected_model):
    database = Database(tmp_path / "model-migration.sqlite3")
    database.set_setting("model", legacy_model)

    loaded = SettingsService(database).load()

    assert loaded.model == expected_model
    assert database.get_setting("model") == expected_model


def test_unknown_model_preference_falls_back_to_luna(tmp_path):
    database = Database(tmp_path / "unknown-model.sqlite3")
    database.set_setting("model", "unreleased-model-id")

    loaded = SettingsService(database).load()

    assert loaded.model == "gpt-6-luna"
    assert database.get_setting("model") == "gpt-6-luna"


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_existing_reasoning_preferences_are_preserved(tmp_path, effort):
    database = Database(tmp_path / f"reasoning-{effort}.sqlite3")
    database.set_setting("reasoning_effort", effort)

    assert SettingsService(database).load().reasoning_effort == effort


def test_unknown_reasoning_preference_falls_back_to_medium(tmp_path):
    database = Database(tmp_path / "unknown-reasoning.sqlite3")
    database.set_setting("reasoning_effort", "unreleased-effort")

    loaded = SettingsService(database).load()

    assert loaded.reasoning_effort == "medium"
    assert database.get_setting("reasoning_effort") == "medium"
