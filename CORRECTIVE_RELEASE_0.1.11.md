# CutData AI v0.1.11 corrective release

## Scope

This release corrects the Thread Mill regression introduced by the v0.1.10
legacy-operation guard. Thread Mill remains a selectable tool with its existing
operation vocabulary and can now calculate through the normal AI/mock service
path.

## Root cause

The legacy-operation check classified operation text globally. Because Thread
Mill intentionally reuses the existing milling labels, every Thread Mill
operation was treated as a legacy End Mill history value and was blocked before
the service call.

## Implemented fix

- Added tool-aware legacy classification in `operations.py`.
- Thread Mill keeps exactly these current operations:
  Slotting, Profiling, Pocketing, Adaptive / Dynamic Milling, Finishing,
  Plunging, Helical interpolation, and Ramp.
- End Mill, Ball Nose End Mill, Bull Nose / Corner Radius End Mill, Face Mill,
  and Indexable End Mill retain the v0.1.10 legacy-history warning/block.
- Thread Mill continues to use the generic milling layout and derived data.
- Hidden Ball/Bull Nose fields remain excluded from Thread Mill requests.
- Visible-request filtering and exact request hashing remain unchanged.
- The AI prompt now carries concise Thread Mill strategy context.
- `PROMPT_VERSION` is `2026-09-07.2`; `SCHEMA_VERSION` remains `2`.
- Application, package metadata, installer, and documentation versions are
  `0.1.11`.

## Validation

- Focused regression/service tests: 37 passed.
- Full test suite: 155 passed.
- Native visual QA: 40 scenarios rendered, including all eight Thread Mill
  operations in light and dark themes.
- Packaged EXE startup check passed with Qt 6.11.2 and Windows ICU resolution.
- Verified window title: `PPT CutData AI 0.1.11 — CNC Machining Calculator`.
- No real OpenAI API calls or credits were used by the automated validation.

## Installer

`installer/CutData-AI-Setup-0.1.11.exe`

- Size: 42,700,764 bytes
- SHA-256: `DE27550B5B70E145855541A61B943FB74BFB650C64A2F252336464E9639692C5`

The existing Thread Mill labels were deliberately retained for this focused
regression release. A separate terminology redesign can be considered later
without changing the current tool-aware legacy contract.
