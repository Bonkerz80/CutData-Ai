"""Application entry point for ``python -m src.main``."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .cutdata_ai.config.constants import APP_NAME
from .cutdata_ai.config.settings import default_data_dir
from .cutdata_ai.database.database import Database
from .cutdata_ai.ui.main_window import MainWindow, apply_styles


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("CutData AI")
    apply_styles(app)
    database = Database(default_data_dir() / "cutdata_ai.sqlite3")
    window = MainWindow(database)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

