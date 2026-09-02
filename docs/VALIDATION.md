# Validation

What has actually been verified, and how — kept honest and current as each
phase lands. This is the file to check before trusting any claim made
elsewhere in the docs.

## Phase 1 + foundation hardening

- 26/26 tests passing (`pytest`): schema construction/validation/
  permissiveness (7), adapter contract (3), normalization contract incl.
  per-frame provenance (6), replay descriptor hashing/equality (5),
  structured logging (3), plus fixtures.
- No models exist yet, so no model validation to report.
- No latency measurements yet — nothing runs end-to-end yet.
- No backtesting yet — no baseline to compare against yet.

## Phase 2 — telemetry ingestion

- 53/53 tests passing, up from 26. New coverage: the synthetic speed
  profile stays within the configured v_max and respects corner apex
  speeds (with small discretization slack); generator determinism given a
  fixed seed, including under severe injected noise; different seeds
  produce different noise patterns; tyre age and fuel evolve correctly
  across laps; the schema-validity of every generated frame; both concrete
  adapters (drop/duplicate packet handling, determinism, JSONL round-trip);
  the placeholder real-car adapter's `NotImplementedError` behavior; and
  ingestion's three error-isolation guarantees (malformed frame, failing
  adapter, failing sink each logged/counted without stopping the rest of
  the pipeline).
- Found and fixed during this phase, before it could compound: an initial
  design would have compared a fixed deterministic simulated-time anchor
  against real wall-clock `ingest_timestamp` as a "latency" figure, which
  is meaningless (they're different time domains) outside of realtime-paced
  delivery. Fixed by re-anchoring to real time only when
  `SimulatorAdapter(realtime=True)`; batch/test mode keeps the fixed
  anchor. Also caught before landing: noise injection was about to write
  simulator-only ground-truth tags into `RaceTelemetry.data_quality_flags`,
  which is documented as reserved for the normalization pipeline's own
  findings — moved to a separate `NoiseResult.injected` side channel instead.
- No claim that the physics model matches any real car's behavior — see
  the "illustrative constants" notes in `simulator/generator/physics.py`
  and `ground_truth.py`.

## Phase 3 — normalization / data quality

- 75/75 tests passing, up from 53. Every stage has direct unit tests
  (NaN→missing, unit conversion, timestamp jitter correction, duplicate
  drop by sequence_id and by content fallback, LOCF missing-data handling,
  negative-tyre-age and impossible-speed clamping, temperature-spike
  detection against stable history, EMA smoothing of a noisy reading,
  cross-frame feature extraction, confidence-score penalty from recorded
  issues). An end-to-end test runs the full 10-stage pipeline against a
  `SimulatorAdapter` stream under `NoiseConfig.severe()` and checks: no
  NaNs survive, timestamps strictly increase, hard physical bounds hold,
  every surviving frame has a confidence score, at least one duplicate was
  actually dropped, and issues were recorded. A separate determinism test
  confirms the same input sequence always normalizes identically.
- Found and fixed during this phase: two of my own test assumptions were
  wrong, not the implementation. (1) A test expected exactly one missing-
  data warning but every LOCF-eligible field on a bare test frame is `None`
  by default, so five warnings are correct. (2) A test generated frames
  directly from `TelemetryGenerator.frames()` and expected transport-level
  duplicates, but duplication is deliberately applied at the
  `SimulatorAdapter` layer, not by the generator itself (see
  simulator/generator/core.py's docstring) -- fixed by routing the test
  through the adapter.
- **Documented, known limitation:** `SpikeDetectionStage`'s fixed z-score
  threshold can mistake a legitimate hard-braking event for a spike, or
  miss one inside an already-noisy window. Thresholds are set
  conservatively (wide) to favor precision over recall; a production
  version would condition the expected value on track position, which this
  pipeline deliberately doesn't have access to. No claim is made that spike
  detection is complete or optimal.

## What's intentionally NOT claimed

- No claim of real F1 telemetry access or FIA integration.
- No claim of production readiness.
- No claim that any predictive model outperforms a naive baseline until
  Phase 20 (backtesting) actually measures it. If it doesn't, that will be
  reported here plainly, not hidden.

This section grows as each phase lands; see [docs/PROGRESS.md](PROGRESS.md)
for phase-by-phase status and [docs/MODELS.md](MODELS.md) for per-model
validation methodology once models exist.
