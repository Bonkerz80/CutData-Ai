# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

# Developer tools on PATH can supply ICU builds with incompatible exports.
windows_root = Path(os.environ['SystemRoot'])
os.environ['PATH'] = os.pathsep.join(map(str, (
    Path(sys.executable).parent, Path(sys.base_prefix),
    Path(sys.base_prefix) / 'DLLs', windows_root / 'System32', windows_root,
)))


a = Analysis(
    ['run_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hook_qt.py'],
    excludes=['PyQt5', 'PyQt6', 'PySide2'],
    noarchive=False,
    optimize=0,
)
# Qt uses the Windows ICU C API. System DLLs/forwarders must stay OS-owned.
def is_windows_component(destination):
    name = Path(destination).name.lower()
    return name in {'icuuc.dll', 'icuin.dll', 'icu.dll', 'ucrtbase.dll'} or name.startswith('api-ms-win-')

a.binaries = [entry for entry in a.binaries if not is_windows_component(entry[0])]
trusted_roots = (Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), windows_root.resolve(), Path(SPECPATH).resolve())
for destination, source, kind in a.binaries:
    if not any(Path(source).resolve().is_relative_to(root) for root in trusted_roots):
        raise RuntimeError(f'Unrelated native dependency was collected: {source}')

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CutData AI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='CutData AI',
)
