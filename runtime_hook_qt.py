"""Load Windows ICU before Qt, avoiding incompatible third-party ICU on PATH.

Qt requires unsuffixed ICU C symbols such as ucnv_open. Other distributions may
only export versioned symbols such as ucnv_open_78, which cannot satisfy Qt.
"""

import ctypes
import os
import sys
from pathlib import Path


_dll_directory_handles = []
_native_library_handles = []


def _prepare_qt_dll_search_path() -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    bundle = Path(sys._MEIPASS)
    pyside = bundle / "PySide6"
    for directory in (pyside, bundle / "shiboken6"):
        if directory.is_dir():
            _dll_directory_handles.append(os.add_dll_directory(str(directory)))

    system_path = ctypes.create_unicode_buffer(32768)
    get_system_directory = ctypes.windll.kernel32.GetSystemDirectoryW
    get_system_directory.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    get_system_directory.restype = ctypes.c_uint
    length = get_system_directory(system_path, len(system_path))
    if not 0 < length < len(system_path):
        raise OSError("Windows system directory could not be determined")
    system_icu = Path(system_path.value) / "icuuc.dll"
    _native_library_handles.append(ctypes.WinDLL(str(system_icu), winmode=0x00000800))

    os.environ["QT_PLUGIN_PATH"] = str(pyside / "plugins")
    os.environ["QML2_IMPORT_PATH"] = str(pyside / "qml")


_prepare_qt_dll_search_path()
