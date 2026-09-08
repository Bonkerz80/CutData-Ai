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

Settings also provides a complete Light / Dark appearance toggle. Light is the default for existing installations; the selected appearance is previewed immediately, restored on Cancel, and persisted in the existing SQLite settings store on Save. It applies to the calculator, read-only result cards, forms, recent list, scrollbars, menus, Settings, About, debug views, banners, badges, selections, and tooltips.

## OpenAI configuration

The default model is `gpt-5.6-luna` with medium reasoning effort. Both can be changed in Settings.

Either set an environment variable before starting the app:

```powershell
$env:OPENAI_API_KEY = "your-key"
py -3 -m src.main
```

Or enter the key in Settings. On Windows, the locally saved key is protected with Windows DPAPI. Settings reports saved-key and environment-key status separately and lets you choose which source is active; the selected source is used consistently by Test Connection and Calculate. The key is never included in prompts, debug output, source code, or cache records.

Use TEST CONNECTION in Settings to verify authentication and access to the selected model. It uses the model lookup endpoint when available, so it does not consume response tokens or write to the machining cache. The calculation integration uses the official OpenAI Python SDK Responses API and a strict JSON schema; it does not scrape conversational text.

## Data and caching

The SQLite database is stored at:

```text
%LOCALAPPDATA%\CutData AI\cutdata_ai.sqlite3
```

Set `CUTDATA_AI_DATA_DIR` to use another data directory, which is useful for a portable development checkout or testing.

Before an API request, the application normalises the complete request and hashes its canonical JSON representation. Numeric forms such as `22`, `22.0`, and `22.00` therefore share a cache entry. Cache records retain the normalised request, model, prompt/schema versions, returned structured data, locally validated data, response metadata, timestamps, and usage count.

Prompt or schema version changes intentionally invalidate older cache entries. A local saved workshop setting is kept separately from the original AI recommendation and takes priority for an exact repeat request.

## Recent calculations

Recent entries show the useful tool identity and operation details rather than timestamps. Double-click a recent calculation to reopen its exact inputs and result. Mock calculations are not persisted as production history.

Saved Tools controls are not exposed. The existing saved-tool table and stored definitions remain intact for a future workflow review.

The complete calculator state is saved in the existing SQLite `app_settings` table. It includes machine/material context, custom material and hardness, the selected tool family, operation, model/reasoning/mock settings, and each tool-family page. State is saved on Calculate, family changes, recent-calculation reopening, and window close. Missing or malformed older state is ignored safely. The last window size and position are also restored when it intersects a current screen; off-screen geometry is clamped back into the available work area.

Results separate three kinds of information:

- **Primary AI recommendation** — the structured machining judgement returned by the selected model and then checked locally.
- **Derived data** — display-only L/D, engagement, DOC ratios, material-removal rate, machine-limit usage, and tapping relationships calculated from known inputs/results.
- **AI context / estimates** — optional model-provided engagement description, setup risk, recommendation summary, spindle power, and spindle torque. Torque can be displayed from the model's power estimate using `9550 × kW ÷ RPM` when torque is not supplied.

Normal results are read-only. The workshop preference editor is not exposed; stored exact-query preferences, database tables and service methods remain available.

Primary cards, applicable secondary and derived rows, and machining notes are visible from startup. Selecting a different tool immediately selects its display layout and clears old values to `—`. Calculations populate those same read-only widgets. AI context appears only when supplied, below the stable calculator display.

The Drill **PECK / Q** card stays visible: `—` before calculation, `Q6 mm` (for example) for an explicit positive AI decision, `NO PECK` for an explicit negative decision, and `NOT SPECIFIED` with a warning for a missing decision. The drilling prompt requires a decision and an intended drilling method; Reamer prompts explicitly require continuous-feed reaming with no peck or drilling cycle. A positive drilling decision without a finite, positive Q, or a false decision with any Q value, is rejected with the existing retry/error handling. If a model still returns peck or drilling-cycle fields for a Reamer, those inapplicable fields are discarded locally and surfaced as a warning; they are never used to create a cycle. Older recent calculations remain readable; contradictory stored no-peck/Q data shows PECK DATA CONFLICT with a verification note. Prompt version `2026-09-07.3` invalidates older prompt cache entries; structured schema version `2` is unchanged.

The forms capture context that materially changes a recommendation, including drill chip evacuation, reaming allowance where known, cutter corner radius and ball-nose contact, setup rigidity, toolholder type, tap type, and indexable insert/cutter details. These values are sent as request context; they are not local cutting-data tables or hidden heuristics.

Milling operation names use the ENCY-style workshop vocabulary: **Roughing Waterline**, **Face Milling**, **Finishing Waterline**, **Finishing Plane**, and **Flat Land Finishing**. End Mill exposes all five; Ball Nose exposes Roughing Waterline, Finishing Waterline, and Finishing Plane; Bull Nose adds Flat Land Finishing; Face Mill exposes Face Milling; and Indexable End Mill exposes Roughing Waterline, Face Milling, and Flat Land Finishing. Thread Mill retains its current operation vocabulary — Slotting, Profiling, Pocketing, Adaptive / Dynamic Milling, Finishing, Plunging, Helical interpolation, and Ramp — while drilling, reaming, and tapping workflows retain their existing operation behaviour. Older generic milling labels remain readable when reopening saved state/history and are never silently remapped.

## Tests

```powershell
py -3 -m pytest -q
```

Tests use fake services and never spend API credits. They cover exact cache identity, numeric normalisation, changed machining conditions, exact workshop-setting precedence, dormant saved-tool data preservation, active request filtering, operation-specific layouts, legacy recalculation protection, deterministic arithmetic and machine limits, no local peck/tap-drill/reaming invention, malformed responses, mock-mode isolation, explicit API-key source migration and routing, settings persistence, UI status, asynchronous connection testing, safe HTTP error classification, coating compatibility, machine-limit migration, and connection-test cache isolation.

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

The result is `installer\CutData-AI-Setup-0.1.12.exe`. It installs per-user under `%LOCALAPPDATA%\Programs\CutData AI`, creates Start Menu and Desktop shortcuts using the official PPT CutData icon, and can be removed from Windows Installed apps. The complete application folder, including the bundled Qt runtime, is included in the installer. User settings and calculation history remain in `%LOCALAPPDATA%\CutData AI` when the application is uninstalled.

Version 0.1.12 keeps the 0.1.11 corrective workflow: Saved Tools and workshop editor controls remain hidden, hidden/inapplicable inputs are excluded from AI requests and exact-cache identities, ENCY operations determine result cards and derived engagement labels, and legacy End Mill history remains readable but blocked from ambiguous recalculation. Thread Mill keeps its existing operation vocabulary as current supported workflow context, so Slotting, Profiling, Pocketing, Adaptive / Dynamic Milling, Finishing, Plunging, Helical interpolation, and Ramp can calculate. API keys now use an explicit saved-key or environment-variable source with safe match status, selected-source routing for Test Connection and Calculate, and clear HTTP failure categories. The built-in HAAS VF-2 limit is corrected to 8,000 RPM with a safe migration for the old shipped value. The centralized coating list includes Cupro (ITC), AlCrN, ZrN, DLC, CVD Diamond, and Other / Proprietary; prompt version `2026-09-07.3` invalidates older prompt cache entries and structured schema version `2` is unchanged. It preserves the complete Light / Dark theme system, live theme preview and persistence, operation-specific labels/fields, per-tool last-used operations, startup placeholders, compact recent-calculation summaries, read-only result values, PPT branding, saved calculator state, exact caching, separate local workshop preferences, Reamer continuous-feed behaviour, and the Qt startup fix. The official `src\cutdata_ai\assets\ppt\ppt-cutdata.ico` remains the Windows product icon. Windows 10 1809 or later (64-bit), or Windows 11, is required.

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
    assets/                       official PPT/CutData AI logos and Windows icon
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
