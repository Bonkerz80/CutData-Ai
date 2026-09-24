"""Render real calculator windows with isolated mock data for visual review.

Run from the project root: .venv-build/Scripts/python -m scripts.qa_ency_ui
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
from src.cutdata_ai.ui.main_window import MainWindow
from src.cutdata_ai.ui.dialogs import AboutDialog, SettingsDialog
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
    output = Path("build/visual-qa-0.1.13")
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
