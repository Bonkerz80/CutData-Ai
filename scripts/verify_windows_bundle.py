"""Release gate for accidental ICU bundling and successful Qt window creation."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

import pefile


def verify_bundle(executable: Path, launch: bool = False) -> None:
    executable = executable.resolve()
    if not executable.is_file():
        raise RuntimeError(f"Missing executable: {executable}")
    root = executable.parent
    unwanted = [p.relative_to(root) for p in root.rglob("*.dll") if (
        p.name.lower().startswith(("icu", "api-ms-win-"))
        or p.name.lower() == "ucrtbase.dll"
    )]
    if unwanted:
        raise RuntimeError(f"Windows system libraries must not be bundled: {unwanted}")
    qt = root / "_internal" / "PySide6" / "Qt6Core.dll"
    system_icu = Path(os.environ["SystemRoot"]) / "System32" / "icuuc.dll"
    with pefile.PE(str(qt)) as qt_pe, pefile.PE(str(system_icu)) as icu_pe:
        required = {i.name for entry in qt_pe.DIRECTORY_ENTRY_IMPORT
                    if entry.dll.lower() == b"icuuc.dll" for i in entry.imports if i.name}
        exported = {entry.name for entry in icu_pe.DIRECTORY_ENTRY_EXPORT.symbols}
        if not required or required - exported:
            raise RuntimeError(f"Windows ICU does not provide the expected Qt exports: {required - exported}")
    print(f"Native dependency check passed: Windows ICU supplies all {len(required)} required Qt symbols.")

    if not launch:
        return
    environment = dict(os.environ)
    windows = Path(os.environ["SystemRoot"])
    environment["PATH"] = os.pathsep.join(map(str, (windows / "System32", windows)))
    for key in list(environment):
        if key.startswith(("QT_", "QML", "PYTHON")):
            environment.pop(key)
    with tempfile.TemporaryDirectory(prefix="cutdata-verify-") as temp:
        report = Path(temp) / "startup.json"
        process = subprocess.Popen([str(executable), "--startup-check", str(report)], env=environment, cwd=temp)
        try:
            exit_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError("Startup did not complete within 30 seconds; an error dialog is not a successful launch") from None
        if exit_code or not report.is_file():
            raise RuntimeError(f"Startup failed: exit={exit_code}, readiness report={report.exists()}")
        result = json.loads(report.read_text(encoding="utf-8"))
        if not result.get("ready") or Path(result.get("icu_path", "")).resolve() != system_icu.resolve():
            raise RuntimeError(f"Unexpected startup result: {result}")
        print("Window startup check passed: " + json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--launch-check", action="store_true")
    args = parser.parse_args()
    verify_bundle(args.executable, args.launch_check)
