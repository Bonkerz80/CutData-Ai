# CutData AI

CutData AI is a native-feeling Windows workshop calculator for CNC speeds and feeds. It collects the important machining inputs, asks the selected OpenAI model for a structured recommendation, checks the arithmetic locally, and presents the useful values as a calculator result rather than a chat transcript.

The first working version includes complete workflows for:

- drilling
- reaming
- rigid tapping
- end milling, including ball nose and bull nose variants
- basic indexable/face-mill inputs

The project is deliberately modular so more cutter families and machine profiles can be added without changing the cache format.

## Run it

Windows with Python 3.10 or newer:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3 -m pip install -r requirements.txt
py -3 -m src.main
```

If no API key is configured, the application opens in clearly labelled development/mock mode. Mock results are useful for exercising the complete interface but are never written to the production cache.

## OpenAI configuration

The default model is `gpt-5.6-luna` with medium reasoning effort. Both can be changed in Settings.

Either set an environment variable before starting the app:

```powershell
$env:OPENAI_API_KEY = "your-key"
py -3 -m src.main
```

Or enter the key in Settings. On Windows, the locally saved key is protected with Windows DPAPI. The key is never included in prompts, debug output, source code, or cache records.

Turn off development/mock mode in Settings when using the API. The integration uses the official OpenAI Python SDK Responses API and a strict JSON schema; it does not scrape conversational text.

## Data and caching

The SQLite database is stored at:

```text
%LOCALAPPDATA%\CutData AI\cutdata_ai.sqlite3
```

Set `CUTDATA_AI_DATA_DIR` to use another data directory, which is useful for a portable development checkout or testing.

Before an API request, the application normalises the complete request and hashes its canonical JSON representation. Numeric forms such as `22`, `22.0`, and `22.00` therefore share a cache entry. Cache records retain the normalised request, model, prompt/schema versions, returned structured data, locally validated data, response metadata, timestamps, and usage count.

Prompt or schema version changes intentionally invalidate older cache entries. A local saved workshop setting is kept separately from the original AI recommendation and takes priority for an exact repeat request.

## Saved tools and recent calculations

Use **Save current tool** to save a tool definition as a named favourite. Selecting it later repopulates the relevant tool fields. Saved tools are stored in SQLite and are designed to become a fuller tool library later.

Double-click a recent calculation to reopen its inputs and result. Mock calculations are not persisted as production history.

## Tests

```powershell
py -3 -m pytest -q
```

Tests use fake services and never spend API credits. They cover numeric normalisation, all core arithmetic relationships, RPM limits, malformed responses, cache persistence and invalidation, mock-mode isolation, and workshop-setting precedence.

## Windows executable

With the dependencies installed, run:

```powershell
.\build_windows.ps1
```

The result is `dist\CutData AI\CutData AI.exe`. The executable does not require Python on the target machine. User data remains in `%LOCALAPPDATA%\CutData AI`.

## Full Windows installer

Install Inno Setup 7, then run:

```powershell
.\build_installer.ps1
```

The result is `installer\CutData-AI-Setup-0.1.1.exe`. It installs per-user under `%LOCALAPPDATA%\Programs\CutData AI`, creates Start Menu and Desktop shortcuts, and can be removed from Windows Installed apps. The complete application folder, including the bundled Qt runtime, is included in the installer. User settings and calculation history remain in `%LOCALAPPDATA%\CutData AI` when the application is uninstalled.

Version 0.1.1 fixes the `ucnv_open` / `QtWidgets` startup failure by removing an incompatible ICU DLL bundled in 0.1.0. Install 0.1.1 over the existing installation to remove the obsolete files automatically. Windows 10 1809 or later (64-bit), or Windows 11, is required.

Builds isolate native dependency discovery from developer tools on PATH. Qt uses the Windows ICU library; copying another application's `icuuc.dll` into the application directory will break its ABI. Before an installer is compiled, the release gate checks every ICU function imported by Qt against Windows. The following additional check starts the actual packaged window with a clean environment and verifies the loaded ICU path:

```powershell
.\.venv-build\Scripts\python.exe scripts\verify_windows_bundle.py "dist\CutData AI\CutData AI.exe" --launch-check
```

## Project map

```text
src/
  main.py                         application entry point
  cutdata_ai/
    config/                       name, defaults, materials, paths
    models/                       requests, results, strict response schema
    database/                     SQLite tables and repositories
    prompts/                      reusable machining system/user prompts
    services/                     normalisation, cache flow, validation, SDK
    ui/                           PySide6 forms, result panel, settings
tests/                            offline automated tests
```

## Important calculation rules

The application independently verifies the relationships that matter at the machine:

```text
Vc = π × D × RPM / 1000
Milling feed = RPM × flute/insert count × feed per tooth
Drilling/reaming feed = RPM × feed per rev
Rigid tapping feed = RPM × exact pitch
```

The selected machine's maximum RPM and feed are applied locally. Any correction is recorded in the Advanced / Debug view and surfaced as a warning in the result notes.
