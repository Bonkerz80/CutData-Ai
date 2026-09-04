"""Application entry point for ``python -m src.main``."""

from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer, qVersion
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .cutdata_ai.config.constants import APP_NAME, PUBLISHER_NAME, WINDOWS_ICON_PATH
from .cutdata_ai.config.settings import default_data_dir
from .cutdata_ai.database.database import Database
from .cutdata_ai.ui.main_window import MainWindow, apply_styles


def main() -> int:
    # An error dialog also keeps a process alive. Verify an actual rendered window.
    startup_report = None
    temporary_data = None
    if len(sys.argv) == 3 and sys.argv[1] == "--startup-check":
        startup_report = Path(sys.argv[2]).resolve()
        temporary_data = tempfile.TemporaryDirectory(prefix="cutdata-startup-")
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PPT.CutDataAI")
        except Exception:
            # The icon still works when this optional Windows taskbar hint is unavailable.
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(PUBLISHER_NAME)
    app.setWindowIcon(QIcon(str(WINDOWS_ICON_PATH)))
    apply_styles(app)
    data_dir = Path(temporary_data.name) if temporary_data else default_data_dir()
    database = Database(data_dir / "cutdata_ai.sqlite3")
    window = MainWindow(database)
    window.show()
    if startup_report:
        def report_ready():
            try:
                icu_path = ""
                if os.name == "nt":
                    kernel32 = ctypes.windll.kernel32
                    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
                    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
                    kernel32.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
                    kernel32.GetModuleFileNameW.restype = ctypes.c_uint
                    buffer = ctypes.create_unicode_buffer(32768)
                    module = kernel32.GetModuleHandleW("icuuc.dll")
                    if not module or not kernel32.GetModuleFileNameW(module, buffer, len(buffer)):
                        raise RuntimeError("Could not verify the loaded ICU module")
                    icu_path = buffer.value
                visible = window.isVisible() and not window.grab().isNull()
                startup_report.write_text(json.dumps({
                    "ready": visible,
                    "window_title": window.windowTitle(),
                    "qt_version": qVersion(),
                    "icu_path": icu_path,
                }), encoding="utf-8")
                app.exit(0 if visible else 1)
            except Exception:
                app.exit(1)
        QTimer.singleShot(500, report_ready)
    try:
        return app.exec()
    finally:
        if temporary_data:
            temporary_data.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
