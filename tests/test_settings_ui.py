import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QElapsedTimer
from PySide6.QtGui import QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from src.cutdata_ai.database.database import Database
from src.cutdata_ai.services.openai_service import MockOpenAIService, OpenAIService
from src.cutdata_ai.services.settings_service import SecretStore, SettingsService
from src.cutdata_ai.config.constants import (
    APP_VERSION,
    COMPANY_NAME,
    DEFAULT_MODEL,
    ICON_SVG_PATH,
    PRODUCT_TAGLINE,
    REASONING_EFFORT_DISPLAY_NAMES,
    SUPPORTED_MODELS,
    SUPPORTED_REASONING_EFFORTS,
    WINDOWS_ICON_PATH,
    model_display_name,
)
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
        assert dialog.api_key_source.currentData() == "saved"
        assert dialog.active_key_source.text() == "Windows encrypted saved key"
        assert dialog.key_comparison_status.text() == "DIFFERENT"
        assert "secret" not in dialog.connection_status.text().casefold()
        dialog._save()
        assert service.get_saved_api_key() == "saved-secret"
    finally:
        close_widget(dialog, qapp)


def test_settings_dialog_model_and_reasoning_choices_show_friendly_labels(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "model-choices.sqlite3")
    dialog = SettingsDialog(database, SettingsService(database).load())

    try:
        assert [dialog.model.itemData(i) for i in range(dialog.model.count())] == list(SUPPORTED_MODELS)
        assert [dialog.model.itemText(i) for i in range(dialog.model.count())] == [
            "GPT-6.1 Sol", "GPT-6 Luna", "GPT-6 Sol", "GPT-6 Astra"
        ]
        assert dialog.model.currentData() == DEFAULT_MODEL
        assert "Current saved model: GPT-6.1 Sol" in dialog.model_selection_notice.text()
        assert dialog.save_restart_button.text() == "SAVE & RESTART APP"
        dialog.model.setCurrentIndex(dialog.model.findData("gpt-6-astra"))
        assert "Selected GPT-6 Astra" in dialog.model_selection_notice.text()
        assert "not active yet" in dialog.model_selection_notice.text()
        assert [dialog.reasoning.itemData(i) for i in range(dialog.reasoning.count())] == list(
            SUPPORTED_REASONING_EFFORTS
        )
        assert [dialog.reasoning.itemText(i) for i in range(dialog.reasoning.count())] == [
            REASONING_EFFORT_DISPLAY_NAMES[value] for value in SUPPORTED_REASONING_EFFORTS
        ]
        assert dialog.reasoning.currentData() == "medium"
        assert "Default engine for careful tool research" in dialog.findChild(QLabel, "modelRoleHint").text()
    finally:
        close_widget(dialog, qapp)


def test_save_and_restart_persists_selected_model_and_requests_restart(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "save-restart.sqlite3")
    dialog = SettingsDialog(database, SettingsService(database).load())
    try:
        dialog.model.setCurrentIndex(dialog.model.findData("gpt-6-astra"))
        assert database.get_setting("model") is None
        dialog.save_restart_button.click()
        assert dialog.result() == QDialog.Accepted
        assert dialog.restart_requested is True
        assert SettingsService(database).load().model == "gpt-6-astra"
    finally:
        close_widget(dialog, qapp)


def test_settings_dialog_blocks_testing_typed_key_when_environment_source_is_selected(qapp, tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    database = Database(tmp_path / "inactive-entry.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")
    service.set_api_key_source("environment")
    dialog = SettingsDialog(database, service.load())

    try:
        dialog.api_key.setText("new-saved-secret")
        dialog._test_connection()
        assert dialog._connection_thread is None
        assert "not the selected API source" in dialog.connection_status.text()
        assert "new-saved-secret" not in dialog.connection_status.text()
    finally:
        close_widget(dialog, qapp)


def test_settings_dialog_candidate_uses_new_entered_saved_key_exception(qapp, tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    database = Database(tmp_path / "entered-saved.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")
    service.set_api_key_source("saved")
    dialog = SettingsDialog(database, service.load())

    try:
        dialog.api_key.setText("new-saved-secret")
        assert dialog._candidate_api_key() == "new-saved-secret"
        dialog.api_key_source.setCurrentIndex(dialog.api_key_source.findData("environment"))
        assert dialog._candidate_api_key() == "environment-secret"
    finally:
        close_widget(dialog, qapp)


def test_settings_connection_uses_selected_model_reasoning_and_key_source(qapp, tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "connection-route.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")
    service.set_api_key_source("saved")
    dialog = SettingsDialog(database, service.load())
    captured = {}

    class FakeOpenAIService:
        def __init__(self, api_key, model, reasoning_effort):
            captured.update(api_key=api_key, model=model, reasoning_effort=reasoning_effort)
            self.model = model

        def test_connection(self):
            from src.cutdata_ai.services.openai_service import ConnectionTestResult

            return ConnectionTestResult(True, "success", "Connection successful")

    monkeypatch.setattr("src.cutdata_ai.ui.dialogs.OpenAIService", FakeOpenAIService)
    try:
        dialog.model.setCurrentIndex(dialog.model.findData("gpt-6-astra"))
        dialog.reasoning.setCurrentIndex(dialog.reasoning.findData("xhigh"))
        dialog._test_connection()
        timer = QElapsedTimer()
        timer.start()
        while dialog._connection_thread is not None and timer.elapsed() < 3000:
            QTest.qWait(10)

        assert captured == {
            "api_key": "saved-secret",
            "model": "gpt-6-astra",
            "reasoning_effort": "xhigh",
        }
        assert dialog.connection_status.text().startswith("API VERIFIED")
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
        assert service.get_api_key_source() == "environment"
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
        assert window.status_badge.text() == "LIVE AI · GPT-6.1 SOL · SAVED KEY"
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
        assert window.selected_model_label.text() == "MODEL: GPT-6.1 SOL"
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
        assert window.status_badge.text() == "LIVE AI · GPT-6.1 SOL · SAVED KEY"
    finally:
        close_widget(window, qapp)


def test_model_change_offers_a_visible_optional_restart(qapp, tmp_path, monkeypatch):
    database = Database(tmp_path / "model-restart-prompt.sqlite3")
    window = MainWindow(database)
    window.show()
    qapp.processEvents()

    def save_selected_model(dialog):
        dialog.model.setCurrentIndex(dialog.model.findData("gpt-6-astra"))
        dialog._save()
        return dialog.result()

    monkeypatch.setattr(SettingsDialog, "exec", save_selected_model)
    try:
        window._open_settings()
        assert window.settings.model == "gpt-6-astra"
        assert window.ai_service.model == "gpt-6-astra"
        assert window.restart_app_button.isVisible()
        assert "GPT-6 Astra" in window.model_change_notice.text()
        assert "use it now" in window.model_change_notice.text()
        assert window.selected_model_label.text() == "MODEL: GPT-6 ASTRA"
    finally:
        close_widget(window, qapp)


def test_save_and_restart_button_reaches_app_restart(qapp, tmp_path, monkeypatch):
    database = Database(tmp_path / "restart-route.sqlite3")
    window = MainWindow(database)
    restarted = []

    def save_and_restart(dialog):
        dialog.model.setCurrentIndex(dialog.model.findData("gpt-6-astra"))
        dialog.save_restart_button.click()
        return dialog.result()

    monkeypatch.setattr(SettingsDialog, "exec", save_and_restart)
    monkeypatch.setattr(window, "_restart_app", lambda: restarted.append(True))
    try:
        window._open_settings()
        assert restarted == [True]
        assert window.settings.model == "gpt-6-astra"
    finally:
        close_widget(window, qapp)


@pytest.mark.parametrize(
    ("model", "status"),
    [
        ("gpt-6.1-sol", "LIVE AI · GPT-6.1 SOL · SAVED KEY"),
        ("gpt-6-luna", "LIVE AI · GPT-6 LUNA · SAVED KEY"),
        ("gpt-6-sol", "LIVE AI · GPT-6 SOL · SAVED KEY"),
        ("gpt-6-astra", "LIVE AI · GPT-6 ASTRA · SAVED KEY"),
    ],
)
def test_status_badge_names_every_current_model(model, status, qapp, tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / f"status-{model}.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")
    service.set_api_key_source("saved")
    database.set_setting("mock_mode", "0")
    window = MainWindow(database)

    try:
        window.settings.model = model
        window._api_error = False
        window._update_status()
        assert window.status_badge.text() == status
        assert model_display_name(model).upper() in window.selected_model_label.text()
    finally:
        close_widget(window, qapp)


def test_calculation_service_uses_the_same_selected_key_source(qapp, tmp_path, monkeypatch):
    fake_secret_store(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    database = Database(tmp_path / "same-route.sqlite3")
    service = SettingsService(database)
    service.save_api_key("saved-secret")
    service.set_api_key_source("saved")
    database.set_setting("mock_mode", "0")

    captured = []

    class FakeOpenAIService:
        def __init__(self, api_key, model, reasoning_effort):
            captured.append(api_key)

    monkeypatch.setattr("src.cutdata_ai.ui.main_window.OpenAIService", FakeOpenAIService)
    window = MainWindow(database)
    try:
        assert captured[-1] == "saved-secret"
        service.set_api_key_source("environment")
        window._reload_settings()
        assert captured[-1] == "environment-secret"
    finally:
        close_widget(window, qapp)


def test_connection_worker_surfaces_result_without_touching_ui_thread():
    class FakeService:
        model = "gpt-6-luna"

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
        first.workflow_combo.setCurrentIndex(1)
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
        first.settings.model = "gpt-6-sol"
        first.settings.reasoning_effort = "high"
        first.settings.mock_mode = True
        first.settings_service.save(first.settings)
        first._save_calculator_state()
        saved_request = first._collect_request()
        saved_hash = request_hash(normalize_request(saved_request))
    finally:
        close_widget(first, qapp)

    state_service = SettingsService(database)
    legacy_state = state_service.load_json_setting("last_calculator_state")
    legacy_state["global"].update(model="gpt-6-luna", reasoning_effort="low", mock_mode=False)
    state_service.save_json_setting("last_calculator_state", legacy_state)

    second = MainWindow(database)
    try:
        assert second.workflow_mode == "manual"
        assert second.machine_combo.currentText() == "HAAS VF-9"
        assert second.material_combo.currentText() == "304 Stainless"
        assert second.tool_combo.currentText() == "End Mill"
        assert second.pages["drill"].fields["diameter_mm"].value() == 7.5
        assert second.pages["drill"].fields["flute_length_mm"].value() == 22.0
        assert second.pages["drill"].fields["chip_evacuation"].currentText() == "Restricted"
        assert second.pages["end_mill"].fields["diameter_mm"].value() == 12.0
        assert second.pages["end_mill"].fields["setup_rigidity"].currentText() == "Rigid"
        assert second.pages["end_mill"].fields["toolholder_type"].currentText() == "Shrink fit"
        assert second.settings.model == "gpt-6-sol"
        assert second.settings.reasoning_effort == "high"
        assert second.settings.mock_mode is True
        assert second.ai_service.model == "gpt-6-sol"
        assert request_hash(normalize_request(second._collect_request())) == saved_hash
    finally:
        close_widget(second, qapp)


def test_old_calculator_snapshot_cannot_undo_default_model_migration(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    database = Database(tmp_path / "stale-calculator-model.sqlite3")
    database.set_setting("model", "gpt-6-luna")
    SettingsService(database).save_json_setting("last_calculator_state", {
        "global": {"model": "gpt-6-luna", "reasoning_effort": "low", "mock_mode": False},
    })
    window = MainWindow(database)
    try:
        assert window.settings.model == "gpt-6.1-sol"
        assert window.ai_service.model == "gpt-6.1-sol"
        assert database.get_setting("model") == "gpt-6.1-sol"
    finally:
        close_widget(window, qapp)


def test_window_state_is_defensive_and_about_dialog_has_ppt_identity(qapp, tmp_path, monkeypatch):
    assert normalise_window_state({"x": 20, "y": 30, "width": 900, "height": 700, "maximized": "true"})["maximized"] is True
    assert normalise_window_state({"x": 20, "y": 30, "width": 0, "height": 700}) == {}
    assert normalise_window_state("bad") == {}

    dialog = AboutDialog()
    try:
        text = dialog.details.text()
        assert "PPT" in text
        assert "Default engine: GPT-6.1 Sol" in text
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
