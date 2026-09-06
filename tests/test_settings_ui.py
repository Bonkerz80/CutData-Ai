import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel

from src.cutdata_ai.database.database import Database
from src.cutdata_ai.services.openai_service import MockOpenAIService, OpenAIService
from src.cutdata_ai.services.settings_service import SecretStore, SettingsService
from src.cutdata_ai.config.constants import APP_VERSION, COMPANY_NAME, ICON_SVG_PATH, PRODUCT_TAGLINE, WINDOWS_ICON_PATH
from src.cutdata_ai.services.normalization import normalize_request, request_hash
from src.cutdata_ai.ui.dialogs import AboutDialog, ConnectionTestWorker, SettingsDialog
from src.cutdata_ai.ui.main_window import MainWindow, apply_styles, normalise_window_state


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


def test_appearance_switch_previews_cancel_restores_and_save_persists(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    apply_styles(qapp, "light")
    database = Database(tmp_path / "appearance-dialog.sqlite3")
    service = SettingsService(database)
    dialog = SettingsDialog(database, service.load())

    try:
        assert dialog.appearance_switch.text() == "LIGHT MODE"
        dialog.appearance_switch.setChecked(True)
        qapp.processEvents()
        assert qapp.property("cutdataAppearance") == "dark"
        dialog._cancel()
        assert qapp.property("cutdataAppearance") == "light"
    finally:
        close_widget(dialog, qapp)

    saved = SettingsDialog(database, service.load())
    try:
        saved.appearance_switch.setChecked(True)
        saved._save()
        assert service.load().appearance == "dark"
        assert qapp.property("cutdataAppearance") == "dark"
    finally:
        close_widget(saved, qapp)
        apply_styles(qapp, "light")


def test_main_window_applies_saved_dark_theme_before_show(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    apply_styles(qapp, "light")
    database = Database(tmp_path / "dark-startup.sqlite3")
    database.set_setting("appearance", "dark")
    window = MainWindow(database)
    try:
        assert qapp.property("cutdataAppearance") == "dark"
        assert window.settings.appearance == "dark"
    finally:
        close_widget(window, qapp)
        apply_styles(qapp, "light")


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


def test_main_window_uses_the_official_ppt_header_hierarchy(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "header.sqlite3")
    window = MainWindow(database)

    try:
        assert window.header_frame.objectName() == "brandHeader"
        assert window.header_frame.height() == 88
        assert window.ppt_brand_block.objectName() == "pptBrandBlock"
        assert window.header_product.text() == "CutData AI"
        assert window.header_tagline.text() == PRODUCT_TAGLINE
        assert window.about_button.objectName() == "headerButton"
        assert window.settings_button.objectName() == "headerButton"
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


def test_calculator_state_persists_global_and_family_values_without_changing_request_hash(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "calculator-state.sqlite3")
    first = MainWindow(database)
    try:
        first.machine_combo.setCurrentText("HAAS VF-9")
        first.material_combo.setCurrentText("304 Stainless")
        first.custom_material.setText("")
        first.tool_combo.setCurrentText("Drill")
        first.pages["drill"].fields["diameter_mm"].setValue(7.5)
        first.pages["drill"].fields["flute_length_mm"].setValue(22.0)
        first.pages["drill"].fields["chip_evacuation"].setCurrentText("Restricted")
        first.tool_combo.setCurrentText("End Mill")
        first.pages["end_mill"].fields["diameter_mm"].setValue(12.0)
        first.pages["end_mill"].fields["setup_rigidity"].setCurrentText("Rigid")
        first.pages["end_mill"].fields["toolholder_type"].setCurrentText("Shrink fit")
        first.settings.model = "gpt-5.6-terra"
        first.settings.reasoning_effort = "high"
        first.settings.mock_mode = True
        first._save_calculator_state()
        saved_request = first._collect_request()
        saved_hash = request_hash(normalize_request(saved_request))
    finally:
        close_widget(first, qapp)

    second = MainWindow(database)
    try:
        assert second.machine_combo.currentText() == "HAAS VF-9"
        assert second.material_combo.currentText() == "304 Stainless"
        assert second.tool_combo.currentText() == "End Mill"
        assert second.pages["drill"].fields["diameter_mm"].value() == 7.5
        assert second.pages["drill"].fields["flute_length_mm"].value() == 22.0
        assert second.pages["drill"].fields["chip_evacuation"].currentText() == "Restricted"
        assert second.pages["end_mill"].fields["diameter_mm"].value() == 12.0
        assert second.pages["end_mill"].fields["setup_rigidity"].currentText() == "Rigid"
        assert second.pages["end_mill"].fields["toolholder_type"].currentText() == "Shrink fit"
        assert second.settings.model == "gpt-5.6-terra"
        assert second.settings.reasoning_effort == "high"
        assert second.settings.mock_mode is True
        assert request_hash(normalize_request(second._collect_request())) == saved_hash
    finally:
        close_widget(second, qapp)


def test_window_state_is_defensive_and_about_dialog_has_ppt_identity(qapp, tmp_path, monkeypatch):
    assert normalise_window_state({"x": 20, "y": 30, "width": 900, "height": 700, "maximized": "true"})["maximized"] is True
    assert normalise_window_state({"x": 20, "y": 30, "width": 0, "height": 700}) == {}
    assert normalise_window_state("bad") == {}

    dialog = AboutDialog()
    try:
        text = dialog.details.text()
        assert "PPT" in text
        assert "CutData AI" in dialog.windowTitle()
        assert COMPANY_NAME in text
        assert dialog.findChild(QLabel, "dialogIdentityVersion").text() == f"Version {APP_VERSION}"
        assert dialog.findChild(QLabel, "dialogSubtitle").text() == PRODUCT_TAGLINE
        assert "LOCALAPPDATA" not in text
        assert "secret" not in text.casefold()
        assert not QIcon(str(ICON_SVG_PATH)).isNull()
        assert not QIcon(str(WINDOWS_ICON_PATH)).isNull()
    finally:
        close_widget(dialog, qapp)
