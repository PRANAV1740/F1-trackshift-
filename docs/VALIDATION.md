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

## Phase 4 — race state estimator

- 83/83 tests passing, up from 75. Covers incremental field updates,
  lap-boundary detection producing a correctly-timed `LapRecord`, a dropped
  (fully-filtered) frame being a safe no-op, per-car state isolation,
  pit-history de-duplication, confidence passthrough, and an end-to-end
  two-lap simulation through the full pipeline + estimator producing a
  sane final state (correct lap/tyre-age, one completed lap record with a
  plausible lap time).
- No bugs found this phase requiring a design change — implementation
  matched the design on first test run.

## Phase 5 — tyre degradation intelligence (the flagship problem)

- 98/98 tests passing, up from 83.
- **Controlled recovery (no model misspecification):** synthetic lap times
  built from the estimator's own assumed fuel/evolution functions plus a
  known injected degradation curve (rate=0.04s/lap, cliff at lap 18) and
  small Gaussian noise (σ=0.05s). Recovered rate 0.04 ± 0.015s/lap, cliff
  lap within ±5 of true, base pace within ±1s. This isolates the
  regression machinery from the physics-assumption question.
- **Realistic recovery (with model misspecification, against the real
  simulator's ground truth):** two independently-generated 20-lap stints
  on MEDIUM (true linear rate 0.028s/lap, true cliff at lap 22), pooled and
  fit. Result: **Pearson correlation 0.974** between the fitted and true
  degradation-vs-age curves over the observed range, **mean absolute error
  0.15s**. The fitted linear rate (0.0099s/lap) and cliff-lap point
  estimate (3, vs. true 22) were both substantially off in isolation —
  documented and explained, not hidden: with no observations anywhere near
  the true cliff (laps 0–19 only), the cliff location is fundamentally
  underdetermined from this data, and the grid search is free to trade a
  lower linear rate for an earlier, smaller cliff term that fits the
  *observed* range just as well. The model's own `cliff_posterior`
  correctly reflects this: it is diffuse (no candidate lap carries more
  than ~3% of the posterior mass) rather than falsely confident, so
  `cliff_probability_within()` reports honest, moderate uncertainty (0.49
  at age 19 with a 3-lap lookahead) rather than near-certainty. **The
  practically useful claim — how much slower the tyre will be at ages
  actually observed or nearby — is well recovered (0.15s MAE); the
  specific cliff-lap point estimate is not reliable this far from the true
  cliff, and the model is honest about that via its posterior rather than
  presenting a single confident number.**
- **A real bug caught and fixed, not just tolerance-adjusted:** the first
  version of the realistic validation test faked "this is stint 2 of a
  longer race" only when constructing `TyreObservation`s for fitting (an
  after-the-fact lap-number offset), while the underlying simulated
  telemetry was still generated as if it were stint 1 — internally
  inconsistent, since the assumed-evolution removal at the fitting step no
  longer matched what was actually baked into the data. This produced a
  **negative** correlation (-0.79) against ground truth. Root cause
  diagnosed and fixed properly: added `GeneratorConfig.starting_lap` so
  the generator itself can honestly produce a later-stint's data (tyre age
  resets, track evolution continues from the global lap) — a legitimate,
  reusable generator capability (Phase 18 needs exactly this for real
  pit-stop events), not a test-only hack.

## What's intentionally NOT claimed

- No claim of real F1 telemetry access or FIA integration.
- No claim of production readiness.
- No claim that any predictive model outperforms a naive baseline until
  Phase 20 (backtesting) actually measures it. If it doesn't, that will be
  reported here plainly, not hidden.

This section grows as each phase lands; see [docs/PROGRESS.md](PROGRESS.md)
for phase-by-phase status and [docs/MODELS.md](MODELS.md) for per-model
validation methodology once models exist.
