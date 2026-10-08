# PPT CutData AI

CutData AI is a Windows workshop calculator for CNC speeds and feeds. You pick the machine, material and cutter and describe the job; the selected OpenAI model returns a structured recommendation, the app checks the arithmetic and machine limits locally, and the result is shown as calculator cards rather than a chat transcript.

PPT is the publisher: **Precision Press Tools & Engineering Services Ltd**. CutData AI is the product.

It covers drilling, reaming, rigid tapping, end milling (including ball nose and bull nose), thread milling and indexable/face milling.

> The AI is the machining knowledge engine. The app ships no cutting-data tables, and its output is not a safety certification. Always confirm settings against the real tool, workholding, machine and cut.

## Install

Download `CutData-AI-Setup-X.Y.Z.exe` from the [latest release](https://github.com/Bonkerz80/CutData-Ai/releases/latest) and run it. Windows 10 1809 or later (64-bit), or Windows 11, is required; Python is not.

- Installs per-user to `%LOCALAPPDATA%\Programs\CutData AI`, with Start Menu and Desktop shortcuts.
- Settings, tool library and history live in `%LOCALAPPDATA%\CutData AI` and are kept when you update or uninstall.
- With no API key the app opens in clearly labelled **mock mode**, which exercises the whole interface but must not be used as machining advice.

### Updates

The installed app checks this repository's latest release a few seconds after it starts. If a newer version exists, a box shows the release notes and offers **Download and install**, **Open release page**, **Skip this version** or **Later**. The installer is downloaded only from this repository's releases, and its size and published checksum are verified before it runs. The check is silent when there is nothing new or no connection, and it never interrupts a running calculation.

**About** has a **Check for updates** button and a tick box to turn the start-up check off. Running from source never checks by itself.

## Using it

### AI Guided (default)

Guided asks for the actual cutter and the essentials of the physical job; the model chooses the operation, strategy, entry method, pass plan and cutting values.

- Job types are limited to those the selected tool can do, and each tool shows only its own boxes. A drill asks for hole depth, through/blind and an optional pilot hole; a tap fills thread size and pitch from the library tool.
- Tool material and coating start from the library record and can be changed for one calculation without altering the library.
- A **Needs review** tick box marks a library tool whose details are not yet confirmed.
- Coolant, cut priority, stickout, rigidity, entry access and similar facts sit in a collapsed **Setup details** section; they keep their last values and are sent with every request. Optional limits are under **Advanced Overrides**, and numeric maximums are also enforced locally.
- The result puts "What should I do?" and the pass plan above the detailed values.

For a live Guided calculation the app also searches for current tool/material evidence and makes a second, higher-reasoning review request. The reviewer sees up to three nearby Guided calculations for the same machine, material, cutter and setup, treated as unverified context rather than targets. A large change in RPM, cutting speed, chipload or engagement after a small change in the job needs a physical or source-based reason; otherwise the result is marked **REVIEW REQUIRED** and confidence is lowered. If search or the second check is unavailable, the app says so. Untick **Independent AI check** for a quicker single-request result, which is marked "quick result, not cross-checked".

### Advanced / Manual

The detailed operation-specific form for users who already know their inputs. It captures context such as chip evacuation, reaming allowance, corner radius, ball-nose contact, toolholder type and indexable cutter details. Milling operations use the ENCY-style names (Roughing Waterline, Face Milling, Finishing Waterline, Finishing Plane, Flat Land Finishing), offered according to cutter type.

For drilling, the **PECK / Q** card always shows an explicit decision: a Q value, `NO PECK`, or `NOT SPECIFIED` with a warning. Reaming is always continuous feed; any peck or drilling-cycle fields returned for a reamer are discarded and reported.

### Results

- **Primary AI recommendation**: the model's structured values after local checks.
- **Derived data**: L/D, engagement, DOC ratios, material-removal rate, machine-limit usage and tapping relationships calculated from known values.
- **AI context / estimates**: engagement description, setup risk, summary, spindle power and torque.

Primary cards, the pass plan and up to three key warnings are always visible. Everything else, including full notes and research sources, is under **Details**. Results are read-only.

**Recent…** reopens a previous calculation with its exact inputs and result. After a real cut you can record the actual RPM, feed and engagement and a workshop observation against the cutter; these become context for future requests, not fixed rules.

### Tool Library

The library keeps cutter bodies, indexable inserts and workshop observations as separate records. Tools are listed on the left and the selected record is edited on the right; changes save when you leave a box, pick another record or close the window.

- Only the boxes for the chosen tool type are shown. Material and coating are pick lists.
- New tools start with typical values for their type and are named from the entered facts.
- Part numbers and source details sit in a collapsed **Catalogue details** section.
- **ADD** offers a single tool, a set of sizes of one tool, an insert, or an AI look-up. An insert can also be created from the cutter that uses it.
- AI look-up can start from a description, pasted text, a manufacturer URL or a web search restricted to the manufacturer's domain. Values appear in an editable preview with their evidence status, and nothing is saved until **Save to Library**. Claims without returned source evidence are marked AI-inferred.

Starter records are seeded once and never overwrite later edits. Unknown values are left blank rather than guessed. Tool facts are snapshotted into each calculation, so later library edits do not rewrite history.

### Settings

- **Engine**: the default model is GPT-6.1 Sol (`gpt-6.1-sol`) at medium reasoning effort; GPT-6 Luna, GPT-6 Sol and GPT-6 Astra are also offered, with reasoning from Low to Maximum.
- **API key**: enter it in Settings, where it is protected with Windows DPAPI, or set the `OPENAI_API_KEY` environment variable. Settings shows both sources and lets you choose which is active. The key never appears in prompts, debug output or cache records.
- **TEST CONNECTION** verifies authentication and model access without spending response tokens.
- **Mock / Live** switches without restarting. **Light / Dark** appearance previews immediately.

## What is checked locally

```text
Vc = π × D × RPM / 1000
Milling feed = RPM × flute/insert count × feed per tooth
Drilling/reaming feed = RPM × feed per rev
Rigid tapping feed = RPM × exact pitch
```

The selected machine's maximum RPM and feed are enforced. If a feed limit is exceeded, RPM is reduced and the dependent feed recalculated without changing pitch, feed per rev or feed per tooth. Every correction is shown as a warning and recorded in the Advanced / Debug view.

The model decides the machining judgement: speeds, feeds, DOC, stepover, pecking, tap drill, reaming stock, coolant, notes and warnings. The local layer has no cutting-speed tables or fallback formulas for those; it only verifies arithmetic, rejects impossible combinations and enforces hard limits.

## Data and caching

The SQLite database is at `%LOCALAPPDATA%\CutData AI\cutdata_ai.sqlite3`. Set `CUTDATA_AI_DATA_DIR` to use another folder.

Each request is normalised and hashed, so `22`, `22.0` and `22.00` are the same request. The cache key also includes the exact model and the prompt and schema versions (currently `2026-09-28.1` and `3`), so models never reuse each other's answers and a prompt change invalidates older entries. For Guided work the nearby-history comparison is part of the key as well. Changing any relevant condition creates a new request.

A saved workshop setting is kept separately from the AI recommendation and takes priority for an exact repeat request, whichever model is selected. Mock results are never read from or written to the cache or history. Calculator state and window position are restored on start.

## Development

Windows with Python 3.10 or newer:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3 -m pip install -r requirements.txt
py -3 -m src.main
```

### Tests

```powershell
py -3 -m pytest -q
```

Tests use fake services and never spend API credits.

### Build

```powershell
.\build_windows.ps1      # dist\CutData AI\CutData AI.exe
.\build_installer.ps1    # installer\CutData-AI-Setup-X.Y.Z.exe (needs Inno Setup 6 or 7)
```

The installer build refuses to overwrite an existing installer, so bump the version first in `build_installer.ps1`, `installer.iss`, `pyproject.toml` and `src\cutdata_ai\config\constants.py`.

Qt uses the Windows ICU library; copying another application's `icuuc.dll` into the application folder will break it. The release gate checks Qt's ICU imports, and this starts the packaged window in a clean environment:

```powershell
.\.venv\Scripts\python.exe scripts\verify_windows_bundle.py "dist\CutData AI\CutData AI.exe" --launch-check
```

### Publishing a release

For the update box to find a release it must be published (not a draft or pre-release), tagged `vX.Y.Z`, with the installer attached under its built name, `CutData-AI-Setup-X.Y.Z.exe`. The release description is shown in the update box. Per-version notes are in the `RELEASE_NOTES_*.md` files.

### Project map

```text
src/
  main.py                         application entry point
  cutdata_ai/
    config/                       name, defaults, materials, paths
    assets/                       official PPT/CutData AI logos and Windows icon
    models/                       requests, results, strict response schema
    database/                     SQLite tables and repositories
    prompts/                      reusable machining system/user prompts
    services/                     normalisation, cache flow, validation, SDK, library/import, updates
    ui/                           PySide6 calculator, result panel, settings, library and update dialogs
tests/                            offline automated tests
scripts/                          bundle verification and UI QA
```
