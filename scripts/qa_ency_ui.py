"""Render real calculator windows with isolated mock data for visual review.

Run from the project root: .venv-build/Scripts/python -m scripts.qa_ency_ui
No credentials, production database or network calls are used.
"""
import json
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.cutdata_ai.config.constants import WINDOWS_ICON_PATH, tool_family
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import CalculationOutcome, MachiningResult
from src.cutdata_ai.services.normalization import normalize_request
from src.cutdata_ai.services.calculation_service import CalculationService
from src.cutdata_ai.services.openai_service import MockOpenAIService
from src.cutdata_ai.ui.main_window import MainWindow
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
    output = Path("build/visual-qa-0.1.12")
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setWindowIcon(QIcon(str(WINDOWS_ICON_PATH)))
    temporary = tempfile.TemporaryDirectory(prefix="cutdata-visual-")
    window = MainWindow(Database(Path(temporary.name) / "qa.sqlite3"))
    window.resize(1440, 1040)
    window.show()
    cases = iter((theme, case) for theme in ("light", "dark") for case in CASES)
    reports = []
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
