# Architecture — TrackShift 2026 Race Intelligence Engine

Status: **Phase 1 (foundation) complete.** This document describes what
exists, what it's designed to support, and what is explicitly not built
yet. See "Development roadmap" at the bottom for phase-by-phase status.

## Product statement

> We don't predict tyres. We predict decisions.

The official TrackShift problem is tyre degradation isolation. This project
treats that as one intelligence layer inside a broader, simulator-independent
race intelligence engine: telemetry in, explainable strategic decisions out.
Tyre degradation is the flagship layer, not the whole system.

## Pipeline

```
REAL CAR TELEMETRY ──┐
SIMULATOR TELEMETRY ─┼──▶ SOURCE ADAPTERS ──▶ RaceTelemetry (common schema)
HISTORICAL / REPLAY ─┘                              │
                                                      ▼
                                          TELEMETRY NORMALIZATION
                                                      │
                                                      ▼
                                            RACE STATE ESTIMATOR
                                                      │
                        ┌──────────┬──────────┬──────┼──────┬──────────┬──────────┐
                        ▼          ▼          ▼      ▼      ▼          ▼          ▼
                     Tyre        Pace     Racing-  Opponent Weather  Traffic
                  Intelligence Intelligence Line   Intel.  Intel.   Intel.
                                            Intel.
                        └──────────┴──────────┴──────┼──────┴──────────┴──────────┘
                                                      ▼
                                          EVENT DETECTION ENGINE
                                                      │
                                                      ▼
                                          STRATEGY DECISION ENGINE
                                                      │
                                                      ▼
                                     POSITION / OUTCOME PREDICTION
                                                      │
                                                      ▼
                                          PIT WALL + HQ DASHBOARDS
```

**The simulator is a development/validation environment, not a production
dependency.** It is consumed through the exact same `SourceAdapter`
interface as a real telemetry link or a historical replay (see
`backend/adapters/base.py`); nothing downstream of "source adapters" is
allowed to know or care which one is active.

## Repository layout

```
race-intelligence/          (this repo, rooted at E:\f1)
├── frontend/                pitwall, hq, shared components/charts, track viz
├── backend/                 ingestion → normalization → state → intelligence
│                             layers → events → strategy → prediction → ws
├── models/                  fitted ML components, one dir per intelligence area
├── simulator/                generator / scenarios / injectable events / replay
├── radio/                    async transcription + extraction, off the hot path
├── evaluation/                backtesting / metrics / stress tests / latency
├── tests/                    cross-cutting tests (unit + interface + scenario)
└── docs/                     this file, and future ADRs/assumption logs
```

Every `backend/*` intelligence module, `models/*`, `simulator/*`, `radio/*`,
and `evaluation/*` subdirectory not yet implemented has its own `README.md`
stating its status and what it will own, so the empty directories are not
mysterious — check the subdirectory's own README before implementing it.

Module boundaries are enforced by *what each layer is allowed to import*,
not just by directory convention:

- Only `backend/adapters/*` may know a source-specific format.
- Only `backend/normalization/*` may mutate a frame for data-quality reasons
  (interpolate, smooth, reject, reweight confidence).
- Only `backend/state` holds the authoritative, continuously-updated
  `RaceState` that every intelligence module reads/writes.
- Only `backend/strategy` decides PIT/STAY_OUT/etc. `radio/` may surface a
  driver-reported signal, and an LLM (if used at all, e.g. to phrase an
  explanation) may narrate — neither may independently decide whether to pit.
- The frontend talks to the backend only through the documented API/WS
  surface (`backend/websocket`, forthcoming `GET/POST /api/*`), never by
  importing backend intelligence code directly.

## The `RaceTelemetry` schema (`backend/telemetry/schema.py`)

This is the seam that makes the platform simulator-independent: every
adapter's only job is producing this schema, and everything downstream only
ever consumes it.

Design decisions worth calling out explicitly (the prompt requires
documenting anything that affects scientific/engineering validity):

1. **Units live in field names** (`speed_kph`, `fuel_load_kg`,
   `track_temperature_c`, `rain_probability` as a 0–1 fraction) rather than
   as bare names (`speed`) with units left implicit. A unit mismatch
   becomes a naming bug caught by review/autocomplete instead of a silent
   numerical bug.

2. **The schema is deliberately permissive on physical plausibility.** It
   does not reject a negative `tyre_age_laps`, an impossible `speed_kph`, or
   an out-of-range `rain_probability` at construction time — only
   structural correctness (types, enum membership, required fields:
   `source`, `source_timestamp`, `car_id`, `lap`) is enforced. This is a
   deliberate split of responsibility: **detecting and handling implausible
   values is the explicit job of the normalization pipeline** (impossible-
   value detection, spike detection — see below), not the schema. If the
   schema itself rejected bad values, there would be nothing left for those
   normalization stages to do, and a demo could never show "noisy telemetry
   went in, the pipeline caught it." This is exercised directly in
   `tests/test_telemetry_schema.py::test_schema_is_deliberately_permissive_on_physical_plausibility`.

3. **`model_config = ConfigDict(extra="allow")`** plus a `schema_version`
   field. A source adapter can attach an extra, source-specific field
   without a schema change; promote a field into the typed schema once two
   or more sources need it. This satisfies "design the schema so additional
   telemetry can be added later" without speculative fields added up front.

4. **`track_state` (enum) coexists with four booleans**
   (`safety_car`, `vsc`, `yellow_flag`, `red_flag`). Some feeds expose flag
   status only as one consolidated enum; others expose it only as separate
   booleans. Both are on the schema because adapters differ in what they
   natively provide. Reconciling the two into one consistent view (e.g. "if
   `vsc=True` then `track_state` should read `VIRTUAL_SAFETY_CAR`") is a
   normalization concern, to be implemented as a stage in Phase 3 — not
   something the schema enforces structurally.

5. **All timestamps are timezone-aware UTC**, by adapter contract rather
   than schema enforcement (Pydantic v2 does not reject a naive `datetime`
   — see `test_naive_datetime_is_rejected_by_convention`, which documents
   this rather than asserting a rejection that doesn't happen). Adapters
   are responsible for converting source-local time to UTC before
   constructing a frame. `sequence_id` (an adapter-assigned monotonic
   per-car counter) exists alongside `source_timestamp` specifically
   because timestamps alone are not trusted to be reliably ordered once
   jitter/delay is injected (see noise requirements in `simulator/generator`).

6. **`tyre_state`, `sensor_confidence`, and `data_quality_flags` live on the
   frame but are normally `None`/empty on a raw, freshly-ingested frame.**
   `sensor_confidence` and `data_quality_flags` are populated by the
   normalization pipeline; `tyre_state` is typically overwritten by the
   tyre intelligence layer once a frame reaches the race state estimator.
   They're part of the *common* schema (rather than a separate "enriched
   frame" type) so every downstream consumer reads them from one place
   regardless of which layer last touched the frame — including e.g.
   `evaluation` reading the trail back off a stored frame for a decision
   replay.

7. **`opponent_states` on a frame is a raw, per-instant snapshot only**
   (`car_id`, `position`, `gap_s`, `compound`, `tyre_age_laps`). Derived
   opponent intelligence (pace, degradation, pit probability, undercut
   threat) is computed by `backend/opponents` in Phase 14 from a *history*
   of these snapshots, not carried on the frame itself.

8. **Tyre temperature is one value per corner**, not per thermal-camera
   zone (inner/mid/outer). A documented simplification for this prototype;
   revisit if a source adapter needs the finer detail.

## Source adapters (`backend/adapters/base.py`)

`SourceAdapter` is an `abc.ABC` with `connect()`, `disconnect()`,
`stream() -> AsyncIterator[RaceTelemetry]`, and `health() -> AdapterHealth`.
Three concrete adapters are expected (Phase 2): a real telemetry link
(`DataSource.REAL_CAR`), the in-repo simulator
(`DataSource.SIMULATOR`), and a historical/replay reader
(`DataSource.HISTORICAL_REPLAY`). None exist yet — Phase 1 only defines and
tests the contract (`tests/test_adapter_interface.py`, via a dummy
in-memory adapter).

An adapter must pass imperfect frames through as-is (missing fields,
duplicates, out-of-order timestamps, spikes) rather than silently repairing
or dropping them — repair belongs in normalization, where it's visible,
testable, and tunable independent of the adapter.

### Deterministic replay contract (`backend/adapters/replay.py`)

Any adapter whose output must be reproducible (the simulator, the
historical-replay reader — not a real telemetry link) additionally
implements the `ReplayCapable` protocol: one method,
`replay_descriptor() -> ReplayDescriptor`. A `ReplayDescriptor` is a frozen
`(scenario_id, seed, config)` triple with a stable `config_hash` (sha256 of
the canonicalized config) and a `run_id` combining all three. This is the
concrete mechanism behind "same input + seed + configuration → same
output": the scenario suite (Phase 19), evaluation/backtesting (Phase 20),
and demo mode (Phase 29) all log this descriptor alongside their output so
a run can be identified and re-executed exactly.

## Normalization pipeline (`backend/normalization/base.py`)

`NormalizationStage` is an `abc.ABC` with one method,
`process(frame, context, log) -> RaceTelemetry | None` (returning `None`
drops the frame). Two kinds of state are threaded through deliberately kept
separate:

- **`NormalizationContext`** — rolling, cross-frame memory a stage needs
  (previous frame, bounded recent-frame history), scoped per car and living
  for the pipeline's whole lifetime. All cross-frame memory lives here, not
  in stage instances, so a stage stays stateless/swappable and a pipeline
  run stays reproducible from `(frames, initial context)`.
- **`NormalizationRunLog`** — everything a stage records about *this one
  frame* (`NormalizationIssue`s found, `FieldChange`s made), scoped to a
  single `pipeline.process()` call.

`NormalizationPipeline.process(frame)` returns a `NormalizationResult`:
`raw_frame` (exactly as received), `normalized_frame` (or `None` if
dropped, plus `dropped_at_stage`), `issues`, and `changes` — for that frame
only. This is the concrete implementation of telemetry provenance: for
every frame, you can see the original raw values, the final normalized
values, and an explicit list of what changed at which stage and why
(`FieldChange(stage, field, before, after, reason)`), satisfying "never
silently modify telemetry without recording what changed and why."
Confidence is the fourth leg of provenance and lives on the normalized
frame itself (`RaceTelemetry.sensor_confidence`), populated by the
sensor-confidence-scoring stage.

An earlier version of this pipeline accumulated `NormalizationIssue`s
directly on the per-car context with no per-frame scoping — meaning issues
from every frame processed for a car piled up in one unbounded list with no
way to tell which frame produced which issue, and no `changes` concept
existed at all. That was a genuine provenance gap flagged in review and is
why the pipeline now returns a `NormalizationResult` per frame instead of a
bare `RaceTelemetry`; see `docs/PROGRESS.md` for the full list of Phase 1
foundation fixes.

Planned stage order (Phase 3, not yet implemented — `tests/test_normalization_interface.py`
validates the contract today with illustrative dummy stages, including one
that reproduces the "negative tyre age" case from the problem prompt's
extreme-condition test list):

1. Schema/type validation of the raw frame
2. Unit normalization (in case an adapter didn't normalize at the source)
3. Timestamp alignment / jitter correction
4. Duplicate detection
5. Missing-value handling / interpolation
6. Spike detection
7. Impossible-value detection (e.g. negative tyre age, negative speed)
8. Smoothing
9. Feature extraction
10. Sensor-confidence scoring (produces the frame's `sensor_confidence`)

Each stage is expected to *annotate* (`data_quality_flags` on the frame,
plus `NormalizationIssue`/`FieldChange` on the log) rather than silently
discard information wherever possible, so a decision can later be
explained in terms of what the pipeline actually saw and did.

## Observability (`backend/observability/logging.py`)

A small cross-cutting addition made during foundation hardening, ahead of
the full decision-audit-trail work in Phase 25: `get_logger(name)` returns
a namespaced stdlib logger emitting single-line JSON records, and
`log_and_continue(logger, operation, **fields)` is the one sanctioned
catch-and-degrade context manager for genuinely optional subsystems (a
failed weather fetch, radio extraction) — it always logs the exception at
ERROR before continuing, never a bare `except: pass`. It is explicitly not
for the core pipeline (ingestion, normalization, state, strategy), which
must fail loudly per engineering rule 18.

## What is NOT built yet

Everything past Phase 1: ingestion loop, race state estimator, all six
intelligence layers, event detection, strategy engine, position prediction,
simulator/replay, radio pipeline, both dashboards, evaluation/backtesting,
and the public API/WS surface. Each has a stub `README.md` in its directory
stating this and what it will own — see the repository layout above.

No claim is made anywhere in this repository of real F1 telemetry access,
FIA system integration, or production readiness. Interfaces are designed so
such integrations *could* attach later (a real adapter is just another
`SourceAdapter` implementation), but none exist.

## Development roadmap

The live, actively-updated phase tracker (now a 30-phase roadmap, expanded
from the original 18) is [docs/PROGRESS.md](PROGRESS.md) — check there for
current status rather than duplicating a second table here. Each phase:
implement → test → run → inspect output → fix → commit only stable work →
continue → update docs. No phase is skipped or built out of order without
flagging it in PROGRESS.md.

## Testing strategy

Foundation-level tests in `tests/` cover the schema and interfaces
directly:

`tests/test_telemetry_schema.py` — schema construction, required-field
enforcement, enum validation, nested-model round-trips, forward-compat
extra fields, and the deliberate-permissiveness design choice above.

`tests/test_adapter_interface.py` — the `SourceAdapter` ABC rejects
incomplete implementations and a minimal dummy adapter satisfies the
contract end-to-end (`connect` → `stream` → `health` → `disconnect`).

`tests/test_normalization_interface.py` — the `NormalizationStage` ABC,
pass-through/dropping/change-and-issue-recording dummy stages, per-car
context isolation, bounded history, and per-frame (not accumulated)
provenance.

`tests/test_replay_contract.py` — `ReplayDescriptor` hashing/equality
semantics and the `ReplayCapable` runtime-checkable protocol.

`tests/test_observability_logging.py` — namespaced loggers and the
`log_and_continue` degrade-not-crash context manager.

Each subsequent phase adds its own test module(s) alongside its
implementation; see [docs/VALIDATION.md](VALIDATION.md) for what's been
verified and how, and [docs/PROGRESS.md](PROGRESS.md) for current test counts.

Run with:

```bash
pip install -e ".[dev]"
pytest
```
