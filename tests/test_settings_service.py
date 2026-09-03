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


def test_environment_key_takes_priority_over_saved_key(tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    database = Database(tmp_path / "settings.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")

    status = service.get_api_key_status()
    assert service.get_api_key() == "environment-secret"
    assert service.get_api_key_source() == API_KEY_SOURCE_ENVIRONMENT
    assert status.saved_configured is True
    assert status.environment_detected is True


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
