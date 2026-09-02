"""Make the frozen application's own Qt DLLs win Windows loader resolution.

Some Windows machines have Qt DLLs supplied by other applications on PATH.
PyInstaller normally handles this, but an explicit early DLL-directory setup
avoids mixing those binaries with the PySide6 extension modules.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


_dll_directory_handles = []


def _candidate_pyside_directories() -> list[Path]:
    candidates: list[Path] = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        root = Path(frozen_root)
        candidates.extend((root / "PySide6", root / "_internal" / "PySide6", root))
    executable_root = Path(sys.executable).resolve().parent
    candidates.extend((executable_root / "PySide6", executable_root / "_internal" / "PySide6", executable_root))
    return list(dict.fromkeys(path for path in candidates if (path / "Qt6Core.dll").is_file()))


def _write_loader_diagnostic(message: str) -> None:
    try:
        diagnostic_dir = Path(os.environ.get("TEMP", Path.home())) / "CutData AI"
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        (diagnostic_dir / "qt_loader_error.log").write_text(message, encoding="utf-8")
    except Exception:
        pass


def _preload_bundled_qt(pyside_directory: Path) -> None:
    """Load the core Qt chain from the frozen directory by absolute path."""

    if not sys.platform.startswith("win"):
        return
    try:
        dlls = (
            pyside_directory / "Qt6Core.dll",
            pyside_directory / "Qt6Gui.dll",
            pyside_directory / "Qt6Widgets.dll",
            pyside_directory.parent / "shiboken6" / "shiboken6.abi3.dll",
            pyside_directory / "pyside6.abi3.dll",
        )
        for dll in dlls:
            if dll.is_file():
                ctypes.WinDLL(
                    str(dll),
                    winmode=0x00000100 | 0x00001000,
                )
    except (AttributeError, OSError) as error:
        _write_loader_diagnostic(f"CutData AI Qt loader could not preload bundled DLLs: {error!r}\n")


def _prepare_qt_dll_search_path() -> None:
    directories = _candidate_pyside_directories()
    if not directories or not sys.platform.startswith("win"):
        return
    pyside_directory = directories[0]
    shiboken_directory = pyside_directory.parent / "shiboken6"
    try:
        if shiboken_directory.is_dir():
            _dll_directory_handles.append(os.add_dll_directory(str(shiboken_directory)))
        _dll_directory_handles.append(os.add_dll_directory(str(pyside_directory)))
    except (AttributeError, OSError):
        pass
    existing_path = os.environ.get("PATH", "")
    os.environ["PATH"] = (
        str(pyside_directory)
        + os.pathsep
        + str(shiboken_directory)
        + os.pathsep
        + str(pyside_directory.parent)
        + os.pathsep
        + existing_path
    )
    os.environ["QT_PLUGIN_PATH"] = str(pyside_directory / "plugins")
    os.environ["QML2_IMPORT_PATH"] = str(pyside_directory / "qml")
    _preload_bundled_qt(pyside_directory)


_prepare_qt_dll_search_path()
