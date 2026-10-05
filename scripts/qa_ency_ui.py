"""Render real calculator windows with isolated mock data for visual review.

Run from the project root: .venv/Scripts/python -m scripts.qa_ency_ui
No credentials, production database or network calls are used.
"""
import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from src.cutdata_ai.config.constants import (
    DEFAULT_MODEL,
    SUPPORTED_MODELS,
    SUPPORTED_REASONING_EFFORTS,
    WINDOWS_ICON_PATH,
    model_display_name,
    tool_family,
)
from src.cutdata_ai.config.settings import AppSettings
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import CalculationOutcome, MachiningResult
from src.cutdata_ai.services.normalization import normalize_request
from src.cutdata_ai.services.calculation_service import CalculationService
from src.cutdata_ai.services.openai_service import MockOpenAIService
from src.cutdata_ai.services.tool_import import ToolImportCandidate
from src.cutdata_ai.ui.main_window import MainWindow
from src.cutdata_ai.ui.dialogs import AboutDialog, SettingsDialog
from src.cutdata_ai.ui.tool_import_dialog import ToolImportDialog
from src.cutdata_ai.ui.tool_library_dialog import ToolLibraryDialog, WorkshopFeedbackDialog
from src.cutdata_ai.ui.theme import apply_theme


CASES = [
    ("Startup", "Drill", ""),
    ("Drill", "Drill", ""),
    ("Reamer", "Reamer", ""),
    ("Tap", "Tap", ""),
    ("End-Roughing", "End Mill", "Roughing Waterline"),
    ("End-Plane", "End Mill", "Finishing Plane"),
    ("Ball-Waterline", "Ball Nose End Mill", "Finishing Waterline"),
    ("Ball-Plane", "Ball Nose End Mill", "Finishing Plane"),
    ("Face", "Face Mill", "Face Milling"),
    ("Indexable", "Indexable End Mill", "Roughing Waterline"),
    ("Flat-Land", "End Mill", "Flat Land Finishing"),
    ("Legacy", "End Mill", "Profiling"),
    ("Thread-Slotting", "Thread Mill", "Slotting"),
    ("Thread-Profiling", "Thread Mill", "Profiling"),
    ("Thread-Pocketing", "Thread Mill", "Pocketing"),
    ("Thread-Adaptive", "Thread Mill", "Adaptive / Dynamic Milling"),
    ("Thread-Finishing", "Thread Mill", "Finishing"),
    ("Thread-Plunging", "Thread Mill", "Plunging"),
    ("Thread-Helical", "Thread Mill", "Helical interpolation"),
    ("Thread-Ramp", "Thread Mill", "Ramp"),
]


def main():
    # Keep the screenshot run fully offline even if the parent environment has
    # a user's live key configured.
    os.environ.pop("OPENAI_API_KEY", None)
    output = Path("build/visual-qa-0.2.0")
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    if Path("C:/Windows/Fonts/segoeui.ttf").exists():
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeuib.ttf")
        app.setFont(QFont("Segoe UI"))
    app.setWindowIcon(QIcon(str(WINDOWS_ICON_PATH)))
    temporary = tempfile.TemporaryDirectory(prefix="cutdata-visual-")
    window = MainWindow(Database(Path(temporary.name) / "qa.sqlite3"))
    window.resize(1440, 1040)
    window.show()
    reports = []

    # Review new 0.2.0 surfaces in both themes, including a realistic saved
    # indexable cutter request and a candidate that remains unsaved.
    for theme in ("light", "dark"):
        window.settings.appearance = theme
        apply_theme(app, theme)
        window.workflow_combo.setCurrentIndex(window.workflow_combo.findData("guided"))
        saved_tool = next(item for item in window.tool_library.list_tools() if item["display_name"] == "25 Tipped")
        window.guided_tool_combo.setCurrentIndex(window.guided_tool_combo.findData(saved_tool["id"]))
        window.guided_job_type.setCurrentText("Profile / outside contour")
        window.job_depth.setValue(50)
        window.stock_on_side.setValue(3)
        guided_request = window._collect_request()
        guided_outcome = CalculationService(window.database, MockOpenAIService()).calculate(
            guided_request, window._machine()
        )
        window._show_result(guided_outcome)
        window.result_status.setText("Calculation ready")
        app.processEvents()
        filename = f"{theme}-guided-profile.png"
        assert window.grab().save(str(output / filename))
        reports.append({"theme": theme, "case": "AI Guided profile", "image": filename})

        library_dialog = ToolLibraryDialog(window.tool_library, lambda: None, window)
        library_dialog.resize(1180, 760)
        library_dialog.show()
        app.processEvents()
        filename = f"{theme}-tool-library-tools.png"
        assert library_dialog.grab().save(str(output / filename))
        reports.append({"theme": theme, "case": "Tool library tools", "image": filename})
        library_dialog.tabs.setCurrentIndex(1)
        app.processEvents()
        filename = f"{theme}-tool-library-inserts.png"
        assert library_dialog.grab().save(str(output / filename))
        reports.append({"theme": theme, "case": "Tool library inserts", "image": filename})
        library_dialog.close()
        library_dialog.deleteLater()
        app.processEvents()

        candidate = ToolImportCandidate(
            entity_type="insert",
            display_name="WIDIA XDPT170408PESRMM · WP25PM",
            fields={
                "manufacturer": "WIDIA", "product_family": "VSM17", "designation": "XDPT170408PESRMM",
                "grade": "WP25PM", "geometry": "E", "coating": None,
            },
            field_provenance={
                "manufacturer": {"status": "user_supplied", "confidence": "high", "evidence": "WIDIA", "source_url": ""},
                "designation": {"status": "source_confirmed", "confidence": "high", "evidence": "Product designation shown on official catalogue page", "source_url": "https://www.widia.com/en/products/insert-xdpt"},
                "grade": {"status": "source_confirmed", "confidence": "high", "evidence": "Grade shown on official catalogue page", "source_url": "https://www.widia.com/en/products/insert-xdpt"},
                "geometry": {"status": "ai_inferred", "confidence": "low", "evidence": "Unverified interpretation; check the insert box", "source_url": ""},
                "coating": {"status": "unknown", "confidence": "low", "evidence": "No coating evidence returned", "source_url": ""},
            },
            source_urls=[{"url": "https://www.widia.com/en/products/insert-xdpt", "title": "Official WIDIA product page"}],
            source_title="Official WIDIA product page",
            source_type="manufacturer_webpage",
            source_retrieved_at="2026-09-24T12:00:00+00:00",
            confidence="medium",
        )
        import_dialog = ToolImportDialog(lambda: None, "insert", parent=window)
        import_dialog.method.setCurrentIndex(import_dialog.method.findData("url"))
        import_dialog.manufacturer.setText("WIDIA")
        import_dialog.source_url.setText("https://www.widia.com/en/products/insert-xdpt")
        import_dialog.input_text.setPlainText("XDPT170408PESRMM · WP25PM")
        import_dialog._candidate_ready(candidate)
        import_dialog.resize(1120, 850)
        import_dialog.show()
        app.processEvents()
        filename = f"{theme}-tool-import-preview.png"
        assert import_dialog.grab().save(str(output / filename))
        reports.append({"theme": theme, "case": "AI import review preview", "image": filename})
        import_dialog.close()
        import_dialog.deleteLater()

        feedback_dialog = WorkshopFeedbackDialog(window)
        feedback_dialog.show()
        app.processEvents()
        filename = f"{theme}-workshop-feedback.png"
        assert feedback_dialog.grab().save(str(output / filename))
        reports.append({"theme": theme, "case": "Workshop feedback", "image": filename})
        feedback_dialog.close()
        feedback_dialog.deleteLater()
        app.processEvents()

    # Capture and verify the engine controls in both themes without a key or
    # any network activity; this also checks the About dialog's default label.
    for theme in ("light", "dark"):
        apply_theme(app, theme)
        settings = AppSettings(appearance=theme, mock_mode=True)
        dialog = SettingsDialog(window.database, settings, window)
        dialog.resize(920, 790)
        dialog.show()
        app.processEvents()
        assert [dialog.model.itemData(i) for i in range(dialog.model.count())] == list(SUPPORTED_MODELS)
        assert [dialog.model.itemText(i) for i in range(dialog.model.count())] == [
            model_display_name(model) for model in SUPPORTED_MODELS
        ]
        assert dialog.model.currentData() == DEFAULT_MODEL
        assert [dialog.reasoning.itemData(i) for i in range(dialog.reasoning.count())] == list(
            SUPPORTED_REASONING_EFFORTS
        )
        settings_image = f"{theme}-settings.png"
        assert dialog.grab().save(str(output / settings_image))
        reports.append({"theme": theme, "case": "Settings", "image": settings_image})
        dialog.close()
        dialog.deleteLater()
        app.processEvents()

        about = AboutDialog(window)
        about.show()
        app.processEvents()
        assert f"Default engine: {model_display_name(DEFAULT_MODEL)}" in about.details.text()
        about_image = f"{theme}-about.png"
        assert about.grab().save(str(output / about_image))
        reports.append({"theme": theme, "case": "About", "image": about_image})
        about.close()
        about.deleteLater()
        app.processEvents()

    cases = iter((theme, case) for theme in ("light", "dark") for case in CASES)
    def advance():
        try:
            theme, (name, tool, operation) = next(cases)
        except StopIteration:
            (output / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
            window.close()
            app.quit()
            return
        window.settings.appearance = theme
        apply_theme(app, theme)
        window.workflow_combo.setCurrentIndex(window.workflow_combo.findData("manual"))
        window.tool_combo.setCurrentText(tool)
        page = window.pages[tool_family(tool)]
        if operation:
            page.load_values({"operation": operation})
        window._reset_result_display()
        request = window._collect_request()
        if name == "Legacy":
            result = MachiningResult(rpm=800, feed_mm_min=80, axial_doc_mm=2, radial_doc_mm=1)
            window.database.add_recent("legacy-qa", normalize_request(request), result.to_dict(), "ai")
            window._load_recent()
            window._load_recent_item(window.recent_list.item(0))
        elif name != "Startup":
            outcome = CalculationService(window.database, MockOpenAIService()).calculate(request, window._machine())
            window._show_result(outcome)
        app.processEvents()
        filename = f"{theme}-{name}.png"
        assert window.grab().save(str(output / filename))
        reports.append({"theme": theme, "case": name, "image": filename,
                        "cards": [window.result_titles[k].text() for k, c in window.result_cards.items() if c.isVisible()]})
        QTimer.singleShot(200, advance)
    QTimer.singleShot(500, advance)
    app.exec()
    temporary.cleanup()
    print(f"Rendered {len(reports)} native window scenarios to {output}")


if __name__ == "__main__":
    main()
