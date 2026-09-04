# PPT CutData AI

CutData AI is a native-feeling Windows workshop calculator for CNC speeds and feeds. It collects the important machining inputs, asks the selected OpenAI model for a structured recommendation, checks the arithmetic locally, and presents the useful values as a calculator result rather than a chat transcript.

PPT is the publisher brand: **Precision Press Tools & Engineering Services Ltd**. CutData AI is the product. The application uses the official red/black PPT target and wordmark in a full-width branded header, About/Settings dialogs, Windows executable, taskbar identity, installer, Start Menu shortcut, and desktop shortcut.

The first working version includes complete workflows for:

- drilling
- reaming
- rigid tapping
- end milling, including ball nose and bull nose variants
- basic indexable/face-mill inputs

The AI remains the machining knowledge engine. The application does not ship
material cutting-data tables or local rules intended to replace the model.

## Run it

Windows with Python 3.10 or newer:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3 -m pip install -r requirements.txt
py -3 -m src.main
```

If no API key is configured on first run, the application opens in clearly labelled development/mock mode. The Settings switch lets you choose MOCK MODE ON or LIVE AI MODE without restarting. Mock results are useful for exercising the complete interface but are never written to the production cache.

## OpenAI configuration

The default model is `gpt-5.6-luna` with medium reasoning effort. Both can be changed in Settings.

Either set an environment variable before starting the app:

```powershell
$env:OPENAI_API_KEY = "your-key"
py -3 -m src.main
```

Or enter the key in Settings. On Windows, the locally saved key is protected with Windows DPAPI. Settings reports saved-key and environment-key status separately, with `OPENAI_API_KEY` taking priority. The key is never included in prompts, debug output, source code, or cache records.

Use TEST CONNECTION in Settings to verify authentication and access to the selected model. It uses the model lookup endpoint when available, so it does not consume response tokens or write to the machining cache. The calculation integration uses the official OpenAI Python SDK Responses API and a strict JSON schema; it does not scrape conversational text.

## Data and caching

The SQLite database is stored at:

```text
%LOCALAPPDATA%\CutData AI\cutdata_ai.sqlite3
```

Set `CUTDATA_AI_DATA_DIR` to use another data directory, which is useful for a portable development checkout or testing.

Before an API request, the application normalises the complete request and hashes its canonical JSON representation. Numeric forms such as `22`, `22.0`, and `22.00` therefore share a cache entry. Cache records retain the normalised request, model, prompt/schema versions, returned structured data, locally validated data, response metadata, timestamps, and usage count.

Prompt or schema version changes intentionally invalidate older cache entries. A local saved workshop setting is kept separately from the original AI recommendation and takes priority for an exact repeat request.

## Saved tools and recent calculations

Use **Save current tool** to save a tool definition as a named input preset. Selecting it later repopulates the relevant tool fields; it does not create machining advice or generalise a recommendation.

Double-click a recent calculation to reopen its inputs and result. Mock calculations are not persisted as production history.

The complete calculator state is saved in the existing SQLite `app_settings` table. It includes machine/material context, custom material and hardness, the selected tool family, operation, model/reasoning/mock settings, and each tool-family page. State is saved on Calculate, family changes, saved-tool loading, and window close. Missing or malformed older state is ignored safely. The last window size and position are also restored when it intersects a current screen; off-screen geometry is clamped back into the available work area.

Results separate three kinds of information:

- **Primary AI recommendation** — the structured machining judgement returned by the selected model and then checked locally.
- **Derived data** — display-only L/D, engagement, DOC ratios, material-removal rate, machine-limit usage, and tapping relationships calculated from known inputs/results.
- **AI context / estimates** — optional model-provided engagement description, setup risk, recommendation summary, spindle power, and spindle torque. Torque can be displayed from the model's power estimate using `9550 × kW ÷ RPM` when torque is not supplied.

The forms capture context that materially changes a recommendation, including drill chip evacuation, reaming allowance where known, cutter corner radius and ball-nose contact, setup rigidity, toolholder type, tap type, and indexable insert/cutter details. These values are sent as request context; they are not local cutting-data tables or hidden heuristics.

## Tests

```powershell
py -3 -m pytest -q
```

Tests use fake services and never spend API credits. They cover exact cache identity, numeric normalisation, changed machining conditions, exact workshop-setting precedence, deterministic arithmetic and machine limits, no local peck/tap-drill/reaming invention, malformed responses, mock-mode isolation, API-key source priority, settings persistence, UI status, asynchronous connection testing, and connection-test cache isolation.

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

The result is `installer\CutData-AI-Setup-0.1.5.exe`. It installs per-user under `%LOCALAPPDATA%\Programs\CutData AI`, creates Start Menu and Desktop shortcuts using the PPT-branded product icon, and can be removed from Windows Installed apps. The complete application folder, including the bundled Qt runtime, is included in the installer. User settings and calculation history remain in `%LOCALAPPDATA%\CutData AI` when the application is uninstalled.

Version 0.1.5 keeps the OpenAI setup improvements from 0.1.2 and the architecture corrections from 0.1.3: live machining recommendations come from the selected AI model, while local code only validates deterministic arithmetic and hard machine limits. It adds a substantially stronger PPT/CutData AI visual system using the official legacy artwork, a full-width engineering header, red accent hierarchy, branded dialogs, a packaged multi-size Windows icon, complete calculator-state persistence, screen-safe window restoration, derived result information, and optional structured AI context fields. Deep-hole Q values, tap-drill sizes, and reaming allowances are not manufactured locally. It also retains the 0.1.1 `ucnv_open` / `QtWidgets` startup fix. Windows 10 1809 or later (64-bit), or Windows 11, is required.

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
    assets/                       PPT/CutData AI SVG, PNG, and Windows icon
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

The selected machine's maximum RPM and feed are applied locally. If a feed limit is exceeded, RPM is reduced and the dependent feed is recalculated without changing pitch, feed per rev, or feed per tooth. Any correction is recorded in the Advanced / Debug view and surfaced as a warning in the result notes.

The model decides machining judgement: RPM, cutting speed, feeds, DOC, stepover, pecking and Q, drilling cycle, tap drill, reaming stock, pre-ream size, coolant, notes, and warnings. The local layer does not contain material cutting-speed tables or fallback formulas for those recommendations. It only derives relationships such as cutting speed and feed arithmetic, checks impossible input/result combinations, and enforces hard machine limits. The cache and saved workshop settings are exact canonical-request matches; changing a material, depth, coolant, machine, diameter, or other relevant condition creates a new request.
