# CutData AI 0.1.10 corrective release

## Starting state and scope

The initial local checkout was clean at 0.1.8, commit b9fd4d0. The remote main
branch was inspected and the checkout fast-forwarded to c2e3967, "Add saved
tools and workshop preferences", version 0.1.9. Corrections were made against
that version. The whole commit was not reverted: database additions and the
existing packaging foundation remain.

0.1.9 required correction because it reintroduced the deliberately removed
Saved Tools workflow and added a prominent workshop result editor.

## Changes

1. Application version: 0.1.9 baseline to 0.1.10. Version constants, project
   metadata, installer definition, build output name and README agree.
2. Saved Tools group, selector, Save current/Remove buttons and their
   main-window handlers are removed. Database tables and definitions remain.
3. The workshop editor button/dialog and UI-only editing handlers are removed.
   Exact preference loading, storage and calculation service methods remain.
   Normal results are read-only.
4. Full FieldPage.values() state is still persisted, including hidden values.
   FieldPage.request_values(tool_type) uses explicit operation/subtype
   applicability, independent of whether the window or stacked page is shown.
5. Both canonical normalization and the calculation service apply the same
   filtering. Hidden DOC/Ball Nose fields cannot reach AI or change the cache
   hash; applicable engagement/contact/corner-radius changes do change it.
6. Optional zero pilot/corner/edge/flute/allowance fields are omitted.
   Meaningful false booleans remain. Zero stock is preserved because it can
   describe actual zero stock. Material/hardness context uses applicability
   rather than parent-window visibility, including Toolox 44.
7. The centralized result layout defines these startup and populated cards:

   | Operation | Primary cards |
   | --- | --- |
   | Roughing Waterline | SPINDLE, FEED, DEPTH STEP, RADIAL ENGAGEMENT |
   | Face Milling | SPINDLE, FEED, DEPTH OF CUT, WIDTH OF CUT |
   | Finishing Waterline | SPINDLE, FEED, Z STEP |
   | Finishing Plane | SPINDLE, FEED, STEPOVER |
   | Flat Land Finishing | SPINDLE, FEED, STEPOVER |

8. Derived data follows the same operation semantics. Roughing/facing use
   applicable axial and lateral result values for rectangular MRR. Finishing
   does not calculate MRR from hidden/default dimensions. RPM/feed usage
   remains available. A single lateral-value helper prefers radial engagement
   for roughing/facing and stepover for plane/flat finishing, with an
   absent-value fallback. Waterline finishing has no lateral result.
9. Legacy history reopens without rewriting its operation. The UI and service
   reject new calculations for legacy milling operations before calling AI.
   A warning identifies the old operation. Selecting a current ENCY operation
   allows calculation.
10. New Drill results accept true plus positive finite Q, or false plus null.
    True plus missing/zero/invalid Q and false plus any Q are rejected. No Q
    decision is invented locally. Old contradictory history remains viewable
    as PECK DATA CONFLICT with a verification note.
11. PROMPT_VERSION: 2026-09-05.2 to 2026-09-07.1. SCHEMA_VERSION remains 2.
    The Drill prompt explicitly requires finite positive Q for true and null
    for false. Existing Reamer continuous-feed behavior is retained.

## Validation

Full suite command: `.venv-build\Scripts\python.exe -m pytest -q`.
The suite uses test doubles and mock calculations; no real OpenAI calls or
API credits were used.

Final full-suite result: 148 passed in 423.33 seconds (7 minutes 3 seconds),
including the final legacy Thread Mill and hidden-window material regressions.

The actual source application was rendered in native Windows Qt for all
12 requested scenarios in both Light and Dark modes. All 24 screenshots were
visually inspected. Reproduce with
`.venv-build\Scripts\python.exe -m scripts.qa_ency_ui`.
Screenshots and the scenario/card manifest are in
`build/visual-qa-0.1.10/`. This uses an isolated temporary database.

The Windows bundle was rebuilt with `.\build_windows.ps1 -SkipDependencyInstall`
and the installer with `.\build_installer.ps1`.
The final packaged startup check passed using
`.venv-build\Scripts\python.exe scripts\verify_windows_bundle.py "dist\CutData AI\CutData AI.exe" --launch-check`.
Qt 6.11.2 loaded `C:\WINDOWS\system32\icuuc.dll`; all 20 required ICU
symbols were verified.

Installer: `installer/CutData-AI-Setup-0.1.10.exe` (42,707,208 bytes).
SHA-256: `6B256CD2E50E99CA0AFDEDC09AC9915177836BDCAF9DFD4786D00F49C3015E62`.

## Files changed

- README.md
- pyproject.toml
- installer.iss
- build_installer.ps1
- src/cutdata_ai/config/constants.py
- src/cutdata_ai/config/operations.py
- src/cutdata_ai/models/schema.py
- src/cutdata_ai/prompts/machining.py
- src/cutdata_ai/services/calculation_service.py
- src/cutdata_ai/services/normalization.py
- src/cutdata_ai/ui/dialogs.py
- src/cutdata_ai/ui/main_window.py
- src/cutdata_ai/ui/result_layout.py
- src/cutdata_ai/ui/widgets.py
- tests/test_openai_service.py
- tests/test_workflow_ui.py
- tests/test_corrective_release.py
- scripts/qa_ency_ui.py
- CORRECTIVE_RELEASE_0.1.10.md

## Deliberately deferred

- Saved Tools and workshop override UI redesign.
- Current Thread Mill operation vocabulary: its existing labels are legacy,
  so those records remain readable but cannot create new calculations. No
  ambiguous operation was automatically remapped.
- Live AI evaluation, as requested; all verification was offline.
- GitHub publication and installation over the user's running installation.
  This handoff supplies a local installer and uncommitted corrective changes.

No machining lookup tables, multipliers or unrelated features were added.
PPT artwork, themes, settings, machine profiles, Recent Calculations, async
workers, cache storage and packaging fixes remain in place.
