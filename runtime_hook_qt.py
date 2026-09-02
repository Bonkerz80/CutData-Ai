"""Make the frozen application's own Qt DLLs win Windows loader resolution.

Some Windows machines have Qt DLLs supplied by other applications on PATH.
PyInstaller normally handles this, but an explicit early DLL-directory setup
avoids mixing those binaries with the PySide6 extension modules.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


_dll_directory_handles = []


def _candidate_pyside_directories() -> list[Path]:
    candidates: list[Path] = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        root = Path(frozen_root)
        candidates.extend((root / "PySide6", root / "_internal" / "PySide6"))
    executable_root = Path(sys.executable).resolve().parent
    candidates.extend((executable_root / "PySide6", executable_root / "_internal" / "PySide6"))
    return list(dict.fromkeys(path for path in candidates if (path / "Qt6Core.dll").is_file()))


def _prepare_qt_dll_search_path() -> None:
    directories = _candidate_pyside_directories()
    if not directories or not sys.platform.startswith("win"):
        return
    pyside_directory = directories[0]
    try:
        _dll_directory_handles.append(os.add_dll_directory(str(pyside_directory)))
    except (AttributeError, OSError):
        pass
    existing_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(pyside_directory) + os.pathsep + str(pyside_directory.parent) + os.pathsep + existing_path
    os.environ["QT_PLUGIN_PATH"] = str(pyside_directory / "plugins")
    os.environ["QML2_IMPORT_PATH"] = str(pyside_directory / "qml")


_prepare_qt_dll_search_path()

