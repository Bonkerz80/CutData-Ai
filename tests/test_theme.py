import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel

from src.cutdata_ai.database.database import Database
from src.cutdata_ai.ui.main_window import MainWindow, apply_styles
from src.cutdata_ai.ui.theme import apply_theme


def test_light_and_dark_palettes_change_without_changing_result_widget_types(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app, "light")
    window = MainWindow(Database(tmp_path / "theme.sqlite3"))
    try:
        light_window = app.palette().color(QPalette.Window).name()
        assert app.property("cutdataAppearance") == "light"
        assert all(isinstance(widget, QLabel) for widget in window.result_fields.values())

        apply_theme(app, "dark")
        dark_window = app.palette().color(QPalette.Window).name()
        assert app.property("cutdataAppearance") == "dark"
        assert light_window != dark_window
        assert all(isinstance(widget, QLabel) for widget in window.result_fields.values())
        assert window.notes.isReadOnly()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
        apply_styles(app, "light")

