# PPT CutData AI

CutData AI is a native-feeling Windows workshop calculator for CNC speeds and feeds. It collects the important machining inputs, asks the selected OpenAI model for a structured recommendation, checks the arithmetic locally, and presents the useful values as a calculator result rather than a chat transcript.

PPT is the publisher brand: **Precision Press Tools & Engineering Services Ltd**. CutData AI is the product. The application uses the official red/black PPT target and wordmark in a full-width branded header, About/Settings dialogs, Windows executable, taskbar identity, installer, Start Menu shortcut, and desktop shortcut.

The calculator includes complete workflows for:

- drilling
- reaming
- rigid tapping
- end milling, including ball nose and bull nose variants
- basic indexable/face-mill inputs

The AI remains the machining knowledge engine. The application does not ship
material cutting-data tables or local rules intended to replace the model.
AI Guided is the default workflow; Advanced / Manual retains the detailed
operation-specific form for users who already know their machining inputs.

## Workshop tool library and AI-guided work

The Tool Library keeps cutter bodies, indexable inserts, and workshop
observations as separate records. Linked insert designations, grades, and
geometry are included with the cutter snapshot. Starter records are seeded
once and marked for review where identity or specification details are
incomplete; later startup migrations do not overwrite workshop edits. Known
facts and their field-level provenance are retained, and unknown values are
left blank rather than guessed.

Use the library editor for manual add, edit, duplicate, and delete. AI import
can start from a description, pasted text, a manufacturer URL, or a web search.
For manufacturer lookup, web search is restricted to the supported
manufacturer's domain. Imported values, evidence status, and any surfaced
source links appear in an editable preview; nothing changes until **Save to
Library**. Manufacturer claims not supported by returned source evidence are
marked as AI-inferred, not manufacturer-confirmed. Imports never write to
calculation history or the machining cache.

AI Guided asks for the actual cutter and the essentials of the physical job,
such as profile depth or plate thickness, stock allowance, and finish. Job
types are limited to those the selected tool can do. Coolant, cut priority,
stickout, setup rigidity, entry access, and other optional facts live in a
collapsed **Setup details** section; they keep their last values and are sent
with every request. Optional constraints remain under Advanced Overrides. It intentionally does not require DOC,
radial engagement, stepover, cutting speed, chipload, or an ENCY operation.
The model selects an operation and strategy, entry method, a pass plan, and
the machining values. Numeric maximum overrides are also enforced locally.
Mock mode is visibly marked and must not be used as production advice.

For a live Guided calculation, the app also searches for relevant current
tool/material evidence and makes a separate, higher-reasoning review request
after checking arithmetic and machine limits locally. The reviewer sees up to
three nearby Guided calculations for the same machine, material, cutter, insert,
and setup. Historical AI recommendations are explicitly unverified, not target
values; entries with a contradictory material/hardness combination are
excluded. Large changes in RPM, cutting speed, chipload, or engagement after a
small depth change require an explicit physical or source-based reason. If the
review does not justify the change, the result is marked **REVIEW REQUIRED**
and confidence is lowered. Research links, compared history, and the reviewer
prompt/response are available in the result notes and **Evidence** debug tab.
If live search or the second check is unavailable, the app says so rather than
presenting the result as fully checked. Untick **Independent AI check** for a
quicker result from the first request only; it is marked "quick result, not
cross-checked", and is never reused when the check is ticked. Guided live calculations can use two
AI requests plus web search; this is not a safety certification, and operators
must confirm settings against the real tool, workholding, machine, and cut.

After a real cut, the linked cutter can receive actual RPM/feed/DOC/engagement
and a practical workshop observation. These observations are context for a
future AI request, not deterministic cutting rules. Exact tool/insert facts
are snapshotted into request and history records, so later library edits do
not rewrite past calculations. Cosmetic library names and record revisions do
not by themselves create a different machining-cache identity.

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

The default model is GPT-6.1 Sol (`gpt-6.1-sol`) with medium reasoning effort. Settings also offers GPT-6 Luna, GPT-6 Sol, and GPT-6 Astra. Existing saved GPT-6 Luna defaults move once to GPT-6.1 Sol; a later explicit Luna choice is retained. Reasoning choices are Low, Medium, High, Extra High, and Maximum. Older GPT-5.6 preferences still migrate by tier; unknown saved models fall back to GPT-6.1 Sol.

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

Before an API request, the application normalises the complete machining request and hashes its canonical JSON representation. Numeric forms such as `22`, `22.0`, and `22.00` therefore share a request identity. Production cache identity additionally includes the exact model ID and prompt/schema versions, so switching models cannot reuse another model's answer and switching back can reuse that model's own entry. Cache records retain the model that generated the response, the model-independent normalised machining request, returned structured data, locally validated data, response metadata, timestamps, and usage count. Mock results are visibly marked and neither read from nor written to the production cache.

Prompt or schema version changes intentionally invalidate older cache entries. A local saved workshop setting is kept separately from the original AI recommendation and takes priority for an exact repeat machining request regardless of the selected model. Historical cache and recent-calculation records remain intact; earlier cache entries do not count as GPT-6 cache hits.

For Guided work, the relevant nearby-history comparison is also part of the
model cache identity: a changed comparison context triggers a fresh AI review,
while history does not alter the physical request identity used by saved
workshop preferences.

## Recent calculations

Recent calculations open from the **Recent…** button beside the workflow selector. Entries show the useful tool identity and operation details rather than timestamps. Double-click a recent calculation to reopen its exact inputs and result. Mock calculations are not persisted as production history.

The legacy saved-tool table remains untouched; the normalized workshop library is stored separately.

The complete calculator state is saved in the existing SQLite `app_settings` table. It includes machine/material context, custom material and hardness, the selected tool family, operation, model/reasoning/mock settings, and each tool-family page. State is saved on Calculate, family changes, recent-calculation reopening, and window close. Missing or malformed older state is ignored safely. The last window size and position are also restored when it intersects a current screen; off-screen geometry is clamped back into the available work area.

Results separate three kinds of information:

- **Primary AI recommendation** — the structured machining judgement returned by the selected model and then checked locally.
- **Derived data** — display-only L/D, engagement, DOC ratios, material-removal rate, machine-limit usage, and tapping relationships calculated from known inputs/results.
- **AI context / estimates** — optional model-provided engagement description, setup risk, recommendation summary, spindle power, and spindle torque. Torque can be displayed from the model's power estimate using `9550 × kW ÷ RPM` when torque is not supplied.

Normal results are read-only. Exact-query workshop preferences remain separate from AI recommendations and from the new qualitative observations.

Primary cards are visible from startup; the pass plan and up to three key warnings appear with a result. Secondary and derived rows, the full machining notes, research sources, and AI context sit under **Details**, which is collapsed by default and remembers its last state. Selecting a different tool, in either workflow, immediately selects its display layout and clears old values to `—`. Calculations populate those same read-only widgets.

### Preserved 0.1.13 drilling behavior in Advanced / Manual

The Drill **PECK / Q** card stays visible: `—` before calculation, `Q6 mm` (for example) for an explicit positive AI decision, `NO PECK` for an explicit negative decision, and `NOT SPECIFIED` with a warning for a missing decision. The drilling prompt requires a decision and an intended drilling method; Reamer prompts explicitly require continuous-feed reaming with no peck or drilling cycle. A positive drilling decision without a finite, positive Q, or a false decision with any Q value, is rejected with the existing retry/error handling. If a model still returns peck or drilling-cycle fields for a Reamer, those inapplicable fields are discarded locally and surfaced as a warning; they are never used to create a cycle. Older recent calculations remain readable; contradictory stored no-peck/Q data shows PECK DATA CONFLICT with a verification note. In release 0.1.13, prompt version `2026-09-07.3` invalidated older prompt cache entries and schema version `2` was current.

Advanced / Manual captures applicable context such as drill chip evacuation, reaming allowance, corner radius, ball-nose contact, toolholder type, and indexable cutter details. These are request facts, not local cutting-data tables or hidden heuristics.

Guided results include a recommended operation, practical strategy, entry
method, recommended pass count, and one or more pass-plan stages. Older
structured responses without guided fields remain readable in history; a
guided calculation is rejected if the required operation, strategy, pass
count, or pass plan is absent. The result view puts “What should I do?” and
the pass plan above the detailed calculator values. Prompt version
`2026-09-28.1` and structured schema version `3` identify this contract and
invalidate older prompt/schema cache entries.

Milling operation names use the ENCY-style workshop vocabulary: **Roughing Waterline**, **Face Milling**, **Finishing Waterline**, **Finishing Plane**, and **Flat Land Finishing**. End Mill exposes all five; Ball Nose exposes Roughing Waterline, Finishing Waterline, and Finishing Plane; Bull Nose adds Flat Land Finishing; Face Mill exposes Face Milling; and Indexable End Mill exposes Roughing Waterline, Face Milling, and Flat Land Finishing. Thread Mill retains its current operation vocabulary — Slotting, Profiling, Pocketing, Adaptive / Dynamic Milling, Finishing, Plunging, Helical interpolation, and Ramp — while drilling, reaming, and tapping workflows retain their existing operation behaviour. Older generic milling labels remain readable when reopening saved state/history and are never silently remapped.

## Tests

```powershell
py -3 -m pytest -q
```

Tests use fake services and never spend API credits. They cover exact cache identity, numeric normalisation, changed machining conditions, history matching/exclusion and continuity review, live-search source extraction/fallback, independent-review status and evidence, exact workshop-setting precedence, normalized library seeding/CRUD, insert linking, immutable snapshots, field provenance, import review and isolation, guided/manual workflows, maximum constraints, pass-plan schema, dormant saved-tool data preservation, active request filtering, operation-specific layouts, legacy recalculation protection, deterministic arithmetic and machine limits, no local peck/tap-drill/reaming invention, malformed responses, mock-mode isolation, API-key source routing, settings persistence, UI status, asynchronous connection testing, and safe HTTP error classification.

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

The result is `installer\CutData-AI-Setup-0.2.5.exe`. It installs per-user under `%LOCALAPPDATA%\Programs\CutData AI`, creates Start Menu and Desktop shortcuts using the official PPT CutData icon, and can be removed from Windows Installed apps. The complete application folder, including the bundled Qt runtime, is included in the installer. User settings, workshop library, and calculation history remain in `%LOCALAPPDATA%\CutData AI` when the application is uninstalled.

### Previous-release baseline: 0.1.13

Version 0.1.13 migrated the engine family to GPT-6 Luna, Sol, and Astra, with Luna as the default. Saved model preferences migrated by tier, and reasoning preferences supported Low, Medium, High, Extra High, and Maximum. Production cache keys included exact model and prompt/schema versions while workshop preferences remained tied only to the machining request; historical records were preserved and recent results showed their recorded model. It retained the complete 0.1.12 workflow: filtering hidden/inapplicable inputs, ENCY operations and derived engagement labels, protected legacy End Mill history, Thread Mill operation vocabulary, explicit saved-key/environment-variable source routing, and clear HTTP failure categories. The built-in HAAS VF-2 limit remained corrected to 8,000 RPM with safe migration, and the centralized coating list included Cupro (ITC), AlCrN, ZrN, DLC, CVD Diamond, and Other / Proprietary. Prompt version `2026-09-07.3` and structured schema version `2` were current at that release. Light / Dark themes, operation-specific fields, per-tool last-used operations, startup placeholders, compact recent-calculation summaries, read-only result values, PPT branding, saved calculator state, separate local workshop preferences, Reamer continuous-feed behaviour, and the Qt startup fix remained. The official `src\\cutdata_ai\\assets\\ppt\\ppt-cutdata.ico` remains the Windows product icon. Windows 10 1809 or later (64-bit), or Windows 11, is required.

Builds isolate native dependency discovery from developer tools on PATH. Qt uses the Windows ICU library; copying another application's `icuuc.dll` into the application directory will break its ABI. Before an installer is compiled, the release gate checks every ICU function imported by Qt against Windows. The following additional check starts the actual packaged window with a clean environment and verifies the loaded ICU path:

```powershell
.\.venv\Scripts\python.exe scripts\verify_windows_bundle.py "dist\CutData AI\CutData AI.exe" --launch-check
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
    services/                     normalisation, cache flow, validation, SDK, library/import
    ui/                           PySide6 calculator, result panel, settings, library dialogs
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
