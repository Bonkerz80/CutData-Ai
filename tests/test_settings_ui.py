import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.cutdata_ai.database.database import Database
from src.cutdata_ai.services.openai_service import MockOpenAIService, OpenAIService
from src.cutdata_ai.services.settings_service import SecretStore, SettingsService
from src.cutdata_ai.ui.dialogs import ConnectionTestWorker, SettingsDialog
from src.cutdata_ai.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    application = QApplication.instance() or QApplication([])
    return application


def fake_secret_store(monkeypatch):
    monkeypatch.setattr(SecretStore, "protect", staticmethod(lambda value: f"dpapi:{value}"))
    monkeypatch.setattr(
        SecretStore,
        "unprotect",
        staticmethod(lambda value: value.removeprefix("dpapi:") if value.startswith("dpapi:") else ""),
    )


def close_widget(widget, qapp):
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def test_settings_dialog_blank_key_retains_saved_key_and_reports_both_sources(qapp, tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    database = Database(tmp_path / "dialog.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")
    dialog = SettingsDialog(database, service.load())

    try:
        assert dialog.saved_key_status.text() == "Configured"
        assert dialog.environment_key_status.text() == "Detected"
        assert dialog.active_key_source.text() == "OPENAI_API_KEY environment variable"
        assert "secret" not in dialog.connection_status.text().casefold()
        dialog._save()
        assert service.get_saved_api_key() == "saved-secret"
    finally:
        close_widget(dialog, qapp)


def test_clear_saved_key_only_removes_local_key(qapp, tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    database = Database(tmp_path / "clear-dialog.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")
    dialog = SettingsDialog(database, service.load())

    try:
        dialog._clear_key()
        dialog._save()
        assert service.get_saved_api_key() == ""
        assert service.get_api_key() == "environment-secret"
    finally:
        close_widget(dialog, qapp)


def test_mode_switch_label_and_saved_choice(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "mode-dialog.sqlite3")
    service = SettingsService(database)
    dialog = SettingsDialog(database, service.load())

    try:
        assert dialog.mock_mode.text() == "MOCK MODE ON"
        dialog.mock_mode.setChecked(False)
        assert dialog.mock_mode.text() == "LIVE AI MODE"
        dialog._save()
        assert service.load().mock_mode is False
    finally:
        close_widget(dialog, qapp)


def test_main_window_status_recognises_saved_key_and_service(qapp, tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "main-saved.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")
    database.set_setting("mock_mode", "0")
    window = MainWindow(database)

    try:
        assert window.status_badge.text() == "LIVE AI · GPT-5.6 Luna"
        assert isinstance(window.ai_service, OpenAIService)
    finally:
        close_widget(window, qapp)


def test_live_mode_without_key_stays_live_and_shows_settings_route(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "main-no-key.sqlite3")
    database.set_setting("mock_mode", "0")
    window = MainWindow(database)

    try:
        assert window.status_badge.text() == "NO API KEY"
        assert window.api_status_notice.isHidden() is False
        assert "LIVE AI MODE" in window.api_status_notice.text()
        assert "Open Settings" in window.api_status_notice.text()
        assert window.settings.mock_mode is False
    finally:
        close_widget(window, qapp)


def test_settings_reload_rebuilds_active_service_without_restart(qapp, tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "reload.sqlite3")
    database.set_setting("mock_mode", "1")
    window = MainWindow(database)

    try:
        assert isinstance(window.ai_service, MockOpenAIService)
        SettingsService(database).save_api_key("saved-secret")
        database.set_setting("mock_mode", "0")
        window._reload_settings()
        assert isinstance(window.ai_service, OpenAIService)
        assert window.status_badge.text() == "LIVE AI · GPT-5.6 Luna"
    finally:
        close_widget(window, qapp)


def test_connection_worker_surfaces_result_without_touching_ui_thread():
    class FakeService:
        model = "gpt-5.6-luna"

        def test_connection(self):
            from src.cutdata_ai.services.openai_service import ConnectionTestResult

            return ConnectionTestResult(True, "success", "Connection successful")

    received = []
    worker = ConnectionTestWorker(FakeService())
    worker.finished.connect(received.append)
    worker.run()

    assert received and received[0].success is True
