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

### Concrete stages (`backend/normalization/stages.py`, Phase 3)

`default_pipeline()` assembles ten stages, in this order:

1. **`SchemaValidationStage`** — pydantic's `float` type accepts NaN/Inf as
   structurally valid; this catches that and treats it as missing.
2. **`UnitNormalizationStage`** — folds a small, explicit table of known
   alternate-unit extra fields (e.g. a hypothetical `speed_ms`) into the
   canonical field. Adapters are expected to already emit canonical units;
   this is a safety net, not the primary mechanism.
3. **`TimestampAlignmentStage`** — nudges a non-monotonic `source_timestamp`
   forward to just after the previous frame's, rather than attempting
   reordering (impossible one-frame-at-a-time in a streaming pipeline).
4. **`DuplicateDetectionStage`** — drops an exact repeat, keyed on
   `sequence_id` when available, else on content equality.
5. **`MissingDataHandlingStage`** — last-observation-carried-forward (LOCF)
   on a handful of fast-changing channels (speed, throttle, brake,
   steering, fuel). LOCF is the standard *online* approximation of
   interpolation: true interpolation needs a known point on both sides,
   which a streaming pipeline doesn't have.
6. **`ImpossibleValueDetectionStage`** — clamps values against hard,
   history-independent physical bounds (negative tyre age → 0, speed
   outside [0, 400] kph, percentages outside [0, 100], etc.).
7. **`SpikeDetectionStage`** — flags/clamps values that are statistically
   anomalous versus this car's own rolling history (z-score over
   `context.recent_frames`), even when within hard bounds. Deliberately
   separate from stage 6: impossible-value detection needs no history,
   spike detection needs a rolling window. **Documented limitation:** a
   fixed z-score threshold can mistake a legitimate hard-braking event for
   a spike, or miss a spike inside an already-noisy window's inflated
   variance; thresholds are set conservatively (wide) to favor precision
   over recall. A production version would condition the expected value on
   track position, which this pipeline deliberately has no access to (see
   simulator independence, above).
8. **`SmoothingStage`** — exponential moving average on speed/steering/
   brake/throttle, run *after* impossible-value and spike correction so
   it's smoothing residual jitter, not large corrupted excursions.
9. **`FeatureExtractionStage`** — attaches a small set of cross-frame
   derived features (e.g. `feature_speed_delta_kph`) under `model_extra`,
   for downstream models to consume without recomputing them.
10. **`SensorConfidenceScoringStage`** — aggregates every issue/change
    recorded by the *earlier stages in this same run* (all sharing one
    `NormalizationRunLog` instance) into the frame's `SensorConfidence`.
    This is a genuine summary of what happened to this specific frame, not
    an independently-computed guess.

Each stage *annotates* (`data_quality_flags` on the frame, plus
`NormalizationIssue`/`FieldChange` on the log) rather than silently
discarding information, so a decision can later be explained in terms of
what the pipeline actually saw and did. See
`tests/test_normalization_stages.py` for per-stage tests plus an
end-to-end test running the full pipeline against severe simulator noise
(via `SimulatorAdapter`, which is where transport-level drop/delay/
duplicate corruption is actually applied — `TelemetryGenerator` on its own
only produces sensor-level value noise).

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

## Ingestion (`backend/ingestion`) and concrete adapters (Phase 2)

`IngestionService` runs every configured `SourceAdapter` concurrently,
attaches `ingest_timestamp`, does structural (not value-plausibility)
validation, pushes each frame through a `NormalizationPipeline`, and fans
the `NormalizationResult` out to an `EventBus` and any number of sinks
(Phase 4's race-state estimator will be the first real sink). A malformed
frame, a failing adapter, or a failing sink are each logged and counted in
`IngestionMetrics` without stopping the rest of the pipeline — see
`backend/ingestion/README.md` and `backend/ingestion/service.py`'s
docstring for the exact error-isolation guarantees.

Two concrete adapters exist: `SimulatorAdapter` (wraps
`simulator/generator`'s deterministic physics-informed telemetry, layering
transport-level packet drop/delay/duplicate on top of the generator's
sensor-level noise) and `ReplayAdapter` (replays a stored frame sequence,
in-memory or from a JSONL file). `RealCarAdapter` is a placeholder whose
`connect()`/`stream()` raise `NotImplementedError` — no real telemetry link
exists or is claimed.

`simulator/generator` is a genuinely physics-informed generator (a
simplified point-mass double-pass lap simulation around a fully synthetic,
invented track — see `simulator/generator/README.md`), not a toy random
walk, specifically so it doesn't need to be thrown away and rewritten for
Phase 18 (full event injection: SC/VSC/rain/opponents/pit stops) — Phase 18
extends this module, it does not replace it. Its ground-truth degradation/
fuel/track-evolution models (`simulator/generator/ground_truth.py`) are
kept strictly separate from — and never imported by — the actual
estimators in `backend/tyre`/`backend/pace`, so that Phase 5/6 validation
against known ground truth is meaningful rather than circular.

## Race state (`backend/state`, Phase 4)

`RaceState` (one per car) is the shared object every intelligence module
reads from and writes into — see field-level "populated by Phase N"
comments in `backend/state/race_state.py` for what's real today versus a
reserved placeholder. `RaceStateEstimator` builds it incrementally from a
stream of `NormalizationResult`s and is designed to be plugged straight
into `IngestionService` as a sink; every update is O(1) in the fields
touched, with lap-boundary detection (which finalizes a `LapRecord`) the
only place needing more than the current frame, and even that only needs
the previous frame's lap number, already on the state — no full
recomputation over history per frame.

**Note on "Traffic Intelligence":** the six-layer pipeline diagram at the
top of this document lists Traffic Intelligence as its own box, but the
30-phase roadmap (docs/PROGRESS.md) has no standalone "traffic" phase — it
folds into Phase 6 (Pace Intelligence downweights heavy-traffic laps) and
Phase 14 (Opponent Intelligence tracks gaps/traffic state per opponent).
This is a deliberate reconciliation, not an omission: traffic's effect on
this car's pace and on opponent proximity are the two things "traffic
intelligence" would compute, and both already have a clear home.

## Tyre degradation intelligence (`backend/tyre`, Phase 5)

The flagship problem. Full design (the identifiability argument for why
fuel effect and track evolution are *assumed*, documented functions rather
than freely fit — they're collinear with tyre age within a single stint,
which is a real statistical constraint, not a shortcut) lives in
`backend/tyre/model.py`'s module docstring and `docs/MODELS.md`; validation
methodology and numbers are in `docs/VALIDATION.md`.

One generator change came out of this phase and is worth noting here since
it affects the simulator's contract: `GeneratorConfig.starting_lap` lets a
generation run represent a stint that starts partway through a race (fresh
tyre age, but track evolution continues from the global lap number) —
needed for honest multi-stint validation data, and reusable by Phase 18 for
real pit-stop events rather than being thrown away.

## Pace intelligence (`backend/pace`, Phase 6)

Composes Phase 5's fitted degradation curve (base pace + assumed fuel +
assumed evolution + fitted degradation, evaluated at the car's *current*
age/fuel/lap) into an "expected clean pace right now", compared against
the actual most recent lap's pace, plus a short-window trend slope. Falls
back to a rolling average of recent clean laps early in a stint before
Phase 5 has enough data to fit — labeled distinctly
(`PaceEstimate.source`), never silently blended with the model-based
estimate. `LapRecord.is_clean()` (on `backend/state/race_state.py`) is the
one shared "is this lap usable" predicate, used by both `backend/tyre` and
`backend/pace` so the two don't duplicate or drift on the definition.

## Baseline race trajectory (`backend/state/baseline.py`, Phase 7)

"If current conditions continue, what happens?" — one continuously-
maintained forward projection (not a multi-scenario/counterfactual
simulation), recomputed on lap completion. Future pace/tyre-state
projection and a recommended pit window (from Phase 5's
`remaining_competitive_life_laps`) are genuine, reusing Phase 5/6's fitted
models rather than re-deriving anything. Position, gaps, and finishing
outcome are an **explicitly labeled naive carry-forward** of current
values — the honest baseline given that a real forecast needs Phase 11
(position prediction) and Phase 14 (opponent intelligence), neither built
yet; `BaselineTrajectory.method_note` states this on the object itself so
a consumer can't mistake it for a modeled forecast. There is no dedicated
`backend/baseline` directory — this lives in `backend/state` since it's
fundamentally an extrapolation *of* the race state.

## Event detection engine (`backend/events`, Phase 8)

All 15 event types from the problem statement exist in `EventType`, but
`DETECTOR_STATUS` states plainly that only 6 are live today — the ones
whose evidence already exists (SC/VSC from raw flags, tyre cliff/
degradation-acceleration from Phase 5, pace drop from Phase 6, free pit
window from Phase 7). The rest are honestly marked as waiting on Phases 9,
13, 14, or 15. `EventDetectionEngine.detect(state)` runs after every frame
and edge-triggers against remembered per-car state, so a detector fires
exactly once per transition, not once per frame while a condition holds —
a bug in an early version (no edge-triggering on `PACE_DROP`) would have
spammed one event per frame for the whole lap; caught by a regression test
before it shipped (`tests/test_events.py`).

## Strategy engine (`backend/strategy`, Phase 9)

The only module allowed to decide PIT/STAY_OUT. A pure function
(`decide()`) scoring every candidate against an explicit, fully-documented
objective function — see `docs/STRATEGY.md` for the mathematics and
`docs/VALIDATION.md` for a real off-by-one-lap bug found and fixed in its
horizon accounting during this phase. `UNDERCUT`/`OVERCUT`/`ATTACK`/
`DEFEND` are declared but never selected yet (need Phase 14's opponents);
`expected_position`/`position_gain` are an explicitly-flagged naive
carry-forward pending Phase 11/14.

## Position / outcome prediction (`backend/prediction`, Phase 11)

A genuine Monte Carlo model (`predict_position`): sample this car's and
every opponent's projected remaining-race-time distribution, rank each
draw, report the empirical probability of finishing in each position.
Honestly gated: with no opponent pace model yet (Phase 14) and a
still-single-car simulator, live usage always reports
`source="insufficient_opponent_data"` rather than fabricating a
distribution — the machinery itself is validated with synthetic
multi-opponent test fixtures and ready for Phase 14 to feed real data in
via an injectable `opponent_source`.

## SC/VSC and weather (Phases 12/13)

Phase 12 (SC/VSC) is substantially the union of Phase 8 (`SAFETY_CAR`/
`VSC` event detection) and Phase 9 (event-aware pit-loss reduction as a
term in the strategy objective) — there's no separate SC/VSC module.
What Phase 12 actually added: `simulator/generator/core.py::FlagPeriod`
so SC/VSC can be injected into generated telemetry (setting flags/track
state and capping speed), and `tests/test_sc_vsc_integration.py`, which
proves the full reactive loop end-to-end — an injected SC period produces
exactly one `SAFETY_CAR` event and an immediate strategy reassessment on
that same frame, not a unit-level claim about either piece in isolation.

Phase 13 (`backend/weather`) tracks the actual trend in observed
`rain_probability` (linear regression over a bounded per-car history) to
detect wetting/drying transitions, feeding `RAIN_INCOMING`.
`RaceTelemetry.weather`/`rain_probability` is already the clean
integration point for a real weather feed (any adapter can populate it) —
there is no separate weather-specific adapter, and none is claimed.
`simulator/generator/core.py::WeatherTransition` injects weather changes
into generated telemetry for scenario/demo purposes.

## What is NOT built yet

Past Phase 13: racing-line/opponent intelligence, compound selection's
remaining refinements (traffic/opponent-strategy factors — track
temperature and weather are now available inputs but not yet factored into
compound choice), radio pipeline, both dashboards, evaluation/backtesting,
and the public API/WS surface. Each has a stub `README.md` in its
directory stating this and what it will own — see the repository layout
above and `docs/PROGRESS.md` for current status.

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
