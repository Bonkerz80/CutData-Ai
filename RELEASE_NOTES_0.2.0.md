# CutData AI 0.2.0

CutData AI 0.2.0 makes AI Guided the default while retaining Advanced / Manual
for operators who already know their machining inputs.

## Workshop data

- Added separate normalized cutter-body, insert/tip, and workshop-observation
  tables without replacing the legacy saved-tool table.
- Added a versioned starter library based on the supplied shop list. Known
  facts are carried with field-level provenance; incomplete tool identities
  are clearly marked for review, and unknown catalogue facts remain unknown.
- Added searchable library add/edit/duplicate/delete and shared insert links.
- Added AI-assisted import from partial/manual facts, pasted text, manufacturer
  URLs, or a supported manufacturer-domain web search. Values and evidence are
  editable in a review dialog and are not saved without explicit acceptance.
- Added practical cut feedback for actual RPM/feed/DOC/engagement and workshop
  observations. Feedback is context for future AI advice, not a fixed cutting
  rule.

## Guided machining

- Added a guided job description for profiles, pockets, face work, 3D finishing,
  slots, holes, threads, chamfers, and other physical jobs.
- Job depth, plate thickness, and side stock are represented as workpiece facts,
  separate from model-selected DOC and engagement.
- Added optional operation preferences and numerical maximums. User-entered
  maximum RPM/feed/DOC/engagement/stepover are enforced locally alongside hard
  machine limits.
- Structured guided responses now include recommended operation, strategy,
  entry method, pass count, and a stage-by-stage pass plan.
- Live Guided calculations use current web research and a separate,
  higher-reasoning review of arithmetic, sources, pass planning, and up to
  three nearby same-setup AI calculations. Historical suggestions are labeled
  unverified; material/hardness conflicts are excluded. Material changes after
  small depth changes require an explicit reason or the result is flagged for
  operator review. Missing research/review is surfaced as a warning.
- Added linked cutter/insert facts, setup stickout, rigidity, and relevant
  workshop observations to AI request context.
- Existing calculation history remains readable, and Advanced / Manual remains
  available for the prior detailed input flow.

## Data integrity and release

- Tool and linked-insert identity is captured in normalized requests and
  history. Later library edits do not rewrite stored snapshots. Cosmetic names
  and record revisions alone do not change cache identity; machining-relevant
  fact changes do.
- Importing tool data does not write calculation cache or recent-calculation
  records.
- Prompt version is `2026-09-28.1`; machining response schema version is `3`.
- Application, Python package, and Windows installer versions are `0.2.0`.
- Windows installer remains per-user, with user data stored separately under
  `%LOCALAPPDATA%\CutData AI`.

Mock responses remain explicitly labeled development placeholders and must not
be used as production machining advice.
