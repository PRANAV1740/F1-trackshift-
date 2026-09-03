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

## Phase 6 — pace intelligence

- 108/108 tests passing, up from 98. Covers both estimate sources
  (tyre-model-composed and rolling-average fallback), correct exclusion of
  unclean laps from the average/trend while still surfacing them via
  `current_pace_s`, the delta computation, and trend-slope recovery against
  a known synthetic gradient (0.5s/lap injected, recovered to ±0.01s/lap).
  A wiring test confirms the estimator is lap-boundary-triggered (returns
  the identical cached object, not a recompute, when called again with no
  new completed laps).
- No new fitted parameters introduced in this phase (it composes Phase 5's
  fit), so no separate ground-truth recovery claim is made beyond Phase 5's.

## Phase 7 — baseline race trajectory

- 117/117 tests passing, up from 108. Covers projection with and without a
  fitted degradation estimate, the pit-window recommendation appearing
  only when a remaining-life estimate exists, naive position/gap
  carry-forward, fuel-burn-rate estimation from observed history vs. the
  documented default fallback, and lap-boundary-triggered caching.
- A test-authoring mistake caught and fixed, same pattern as Phase 5/
  Phase 2's findings: I initially asserted projected pace should worsen
  monotonically over the horizon. It doesn't have to — fuel burn-off can
  legitimately make the car faster early in a projection even as the tyre
  degrades (the same effect already validated in
  `test_simulator_generator.py` and `test_tyre_model.py`). Fixed the test
  to check what's actually guaranteed by construction (the degradation
  *component* alone is non-decreasing; total pace equals the documented
  sum of its parts) rather than an emergent property that isn't promised.

## Phase 8 — event detection engine

- 127/127 tests passing, up from 117. Covers rising-edge firing and
  no-repeat-while-held for every live detector, threshold crossing for
  tyre cliff/degradation-acceleration, bounded/per-car event history, and
  a completeness check that every `EventType` has an entry in
  `DETECTOR_STATUS`.
- **A real bug caught by a regression test before it shipped, not after:**
  the first version of `_detect_pace_events` had no edge-triggering at
  all, so it would have emitted a fresh `PACE_DROP` event on every single
  frame for the entire lap that the condition held (dozens of duplicate
  events per lap at the simulator's 5Hz tick rate). Caught immediately by
  writing the "must not spam within the same lap" test alongside the
  other detectors' tests, before running against real simulated data —
  fixed by adding the same edge-triggering memory the other detectors
  already had.

## Phase 9 — strategy engine (and Phase 10's core, compound comparison)

- 143/143 tests passing, up from 127. Covers insufficient-data fallback,
  race-distance-exhausted handling, an imminent-cliff scenario correctly
  producing a PIT/PIT_NEXT_LAP decision with full reasons/risks/
  invalidations, VSC correctly reducing pit loss and being cited in the
  reasons, the `to_dict()` output shape, and lap-/flag-triggered
  reassessment caching.
- **A real, significant bug found and fixed via test-driven development,
  not tolerance-adjusted:** the objective function integrated STAY_OUT
  over the full remaining-race-distance horizon but every PIT candidate
  over one lap less (an attempt to "avoid double-counting the pit lap"
  that was simply wrong), systematically making every pit look about one
  lap's pace cheaper than it actually was. Caught immediately by
  `test_healthy_fresh_tyre_over_a_short_remaining_distance_stays_out`: a
  fresh, healthy MEDIUM tyre with only 7 laps left in the race was
  recommended to pit onto an identical fresh MEDIUM tyre — a ~70-second
  miscalculation with no plausible real justification, unlike the earlier
  "fuel burn-off beats degradation early" findings in Phases 2/5/7, which
  were correct model behavior. Root-caused to the horizon mismatch and
  fixed by integrating every candidate over the identical horizon (see
  `backend/strategy/objective.py::score_pit`'s docstring and
  `docs/STRATEGY.md`). Two dependent tests needed their own scenario
  numbers corrected after the fix — one flipped from "pit wins" to
  "stay-out wins" once the accounting was honest (a gentle cliff
  coefficient of 0.005 genuinely does not outweigh a 22s pit loss even 14
  laps past the cliff — correct, not a bug), and its steeper-cliff
  replacement (`cliff_coefficient=0.05`) does produce the intended
  "severe cliff favors pitting" result.
- Compound comparison (Phase 10's core ask) is exercised by the same
  tests, since `decide()` scores `PIT->SOFT`/`PIT->MEDIUM`/`PIT->HARD`
  candidates directly against each other and against STAY_OUT — there is
  no separate compound-selection test suite because there is no separate
  compound-selection code path to test.

## Phase 11 — position / outcome prediction

- 154/154 tests passing, up from 143. The Monte Carlo model itself is
  validated with synthetic multi-opponent fixtures: a dominant car wins
  P1 in >95% of draws, a much-slower car finishes last in >95%, a close
  field spreads probability across multiple positions, probabilities
  always sum to 1.0, `expected_position` matches manual recomputation, and
  results are deterministic given the same seed.
- The wiring is deliberately tested to prove it does NOT fabricate data:
  an end-to-end run of the full pipeline (ingestion → normalization →
  state → tyre → pace → strategy → prediction) with no opponent source
  configured asserts `source == "insufficient_opponent_data"` on the
  final state, not a plausible-looking but unfounded distribution.
- Minor doc-authoring slip caught and fixed immediately (not a code bug):
  an edit to docs/MODELS.md briefly duplicated the "Pace model" section
  header. Caught by grepping section headers before moving on; fixed by
  merging the split content back together.

## Phases 12-13 — SC/VSC and weather

- 171/171 tests passing, up from 154. New: simulator SC/VSC injection
  (flags/track-state/speed-cap correctly scoped to the injected lap range
  and reverting after), weather-transition injection, weather trend
  detection (rising/falling/stable rain probability, confidence growing
  with history length), and `RAIN_INCOMING` edge-triggering.
- **The most important test added this phase is
  `tests/test_sc_vsc_integration.py`**, which runs the actual pipeline
  (not mocked components) with an injected SC period and asserts: exactly
  one `SAFETY_CAR` event fires (on the rising edge), and the strategy
  engine's decision object identity changes on that same frame — proving
  the "must react automatically" requirement end-to-end rather than
  trusting that Phase 8's edge-triggering and Phase 9's flag-triggered
  reassessment compose correctly just because each passed its own unit
  tests in isolation.
- No new bugs found this round — both pieces (event detection, strategy
  flag-triggering) already had their own correctness established in
  Phases 8-9; this phase's job was proving the composition, which held.

## Phase 14 — opponent intelligence (first multi-car simulation)

- 199/199 tests passing, up from 196. New coverage: `RaceOrderTracker`
  (leader-by-progress ranking, position/gap assignment, non-adjacent gap
  queries), `OpponentSummary`/`pit_probability`/undercut-overcut
  classification (including the "not applicable" cases — an opponent
  behind can't overcut us, one ahead can't undercut us from our
  perspective), the `OpponentIntelligenceEstimator` no-op on a single
  tracked car, six new opponent-aware event detectors (each edge-triggered
  per opponent, with memory correctly pruned when an opponent drops out of
  the tracked set), and `UNDERCUT`/`OVERCUT` relabeling in the strategy
  engine (including the "no relabel without a qualifying opponent" case).
- **Two real, significant bugs found and fixed while building the 3-car
  end-to-end test — not tolerance adjustments, genuine defects:**
  1. **Asyncio scheduling fairness.** The first version of the multi-car
     test showed one car (by whichever adapter `asyncio.gather` happened to
     schedule first) at lap 9 while the other two sat at lap 5, despite no
     pace advantage existing in the generated data. Root cause:
     `SimulatorAdapter.stream()` in non-realtime mode has no `await` point
     in the common case (no delayed/dropped packet that tick), so a single
     adapter's task can run to near-completion before `asyncio.gather`'s
     other tasks get *any* turn — cooperative scheduling only switches
     tasks at actual await points. This is a real correctness issue for
     any multi-car deployment via `IngestionService`, not just a test
     artifact. Fixed with an unconditional `await asyncio.sleep(0)` per
     frame when not in realtime mode.
  2. **Timestamp domain mismatch, recurrence of an already-fixed bug
     class.** After fixing (1), gaps between cars still computed as
     exactly `0.0` even with a clear, deliberate pace differential
     (staggered `starting_fuel_kg`, ~15-20s expected gap by lap 5).
     Direct inspection showed `RaceOrderTracker`'s "elapsed time within
     the current lap" computing as **~244 days** — because it compared
     `current_lap_start_ts` (always derived from `source_timestamp`, the
     fixed-anchor simulated clock) against `ingest_timestamp` (real
     wall-clock time, i.e. whenever the test happened to run). This is
     precisely the same class of bug already found and fixed once in
     Phase 2 (`SimulatorAdapter`'s realtime-anchor handling) — it
     recurred because that lesson wasn't front-of-mind while writing new
     timestamp-comparing code in a different module. Fixed by comparing
     `source_timestamp` against `source_timestamp` consistently.
  3. **A test-methodology dead end, documented rather than hidden:**
     while chasing (2), `v_max_kph` was tried as the pace-differentiation
     knob for the 3-car test and found nearly useless (a 40 kph spread
     produced under 1 second of lap-time difference) — this synthetic
     track's corner spacing means most straights aren't long enough for a
     car to approach anywhere near `v_max` before the next braking zone,
     so corner geometry dominates lap time, not top speed. Confirmed
     directly (`build_speed_profile` at v_max 300/320/340 → 105.58/105.07/
     104.83s). Switched to `starting_fuel_kg`, which acts through the
     ground-truth fuel-effect model directly and produces a robust,
     controllable pace differential. Documented in the test itself so a
     future reader doesn't repeat the same dead end.
  4. Even the FINAL-frame comparison in the test needed care: every car's
     last recorded frame is at (or capped near) the very end of its final
     lap, where the progress-fraction model's `0.999` cap converges for
     every car finishing normally — gaps at that instant are artificially
     compressed regardless of true pace differences (a real, documented
     property of the model's edge behavior, not a bug). The test checks a
     mid-race snapshot instead, for both the gap-positivity assertion and
     the position-prediction-unlocked assertion (the latter has its own
     edge case: `remaining_laps` hits exactly 0 for every car on its final
     frame, correctly triggering the "race distance exhausted" fallback
     and resetting `chosen_projected_time_s` to `None` — also not a bug,
     also required a mid-race check instead).

## Phase 15 — racing-line intelligence

- 211/211 tests passing, up from 207. New coverage in `tests/test_racing_line.py` (4 tests):
  per-corner analysis across all 14 corners on `SyntheticTrack` (`braking_point_m`, `braking_intensity`,
  `entry_speed_kph`, `apex_speed_kph`, `exit_speed_kph`, `line_deviation_m`, `time_loss_s`), line classification
  (`IDEAL`, `ATTACKING`, `DEFENSIVE`), `RacingLineEstimator` state updating and multi-lap time loss tracking,
  and `RACING_LINE_DEGRADATION` event firing on rising edge via `EventDetectionEngine`.

## Phase 16 — radio intelligence

- 217/217 tests passing, up from 211. New coverage in `tests/test_radio.py` (6 tests):
  `RadioIntentExtractor` keyword and pattern matching for driver-reported states (`TYRE_GRAINING`, `TYRE_OVERHEATING`,
  `TYRE_PUNCTURE`, `TRAFFIC_HEAVY`, `RAIN_REPORTED`, `BRAKE_BAL_ISSUE`, `STRATEGY_PIT_REQUEST`, `STRATEGY_STAY_OUT_REQUEST`,
  `UNKNOWN`), `DriverRadioMessage` construction with explicit `is_demo_mode=True`, and `RadioTranscriptionService` async
  non-blocking processing guarantee (`await asyncio.sleep(0)` yield with graceful fallback handling).

## Phase 17 — human/AI disagreement

- 223/223 tests passing, up from 217. New coverage in `tests/test_disagreement.py` (6 tests):
  `HumanAIDisagreementDetector` comparing driver radio reports against telemetry-derived estimators for five distinct conflict types:
  `DRIVER_REPORTS_TYRE_ISSUE_BUT_TELEMETRY_HEALTHY`, `DRIVER_REPORTS_TYRES_FINE_BUT_CLIFF_IMMINENT`,
  `DRIVER_REQUESTS_PIT_BUT_STRATEGY_RECOMMENDS_STAY_OUT`, `DRIVER_REPORTS_RAIN_BUT_WEATHER_DRY`, and
  `DRIVER_REPORTS_TRAFFIC_BUT_GAP_LARGE`.

## Phase 18 — simulator / replay engine

- 207/207 tests passing, up from 199. New coverage in `tests/test_simulator_pit_stop.py` (8 tests):
  `PitStopEvent` stationary phase (`speed_kph = 0.0` in pit box), tyre compound change and age reset,
  pit history record creation and forward propagation, pit-lane speed capping (`EXITING_PIT` phase capped
  to configured pit speed), single-run determinism under noise, multiple pit stops in one run, and an
  end-to-end integration test (`default_pipeline` → `RaceStateEstimator` → `TyreDegradationEstimator`)
  proving that pit laps get `was_pit_lap=True` on their `LapRecord` and are strictly excluded from tyre
  degradation fitting observations.
## Phase 19 — scenario suite

- 232/232 tests passing, up from 223. New coverage in `tests/test_scenarios.py` (9 tests):
  `ScenarioDefinition` catalog of 12 named, seeded scenarios (`normal_race`, `tyre_cliff`, `vsc_pit_opportunity`,
  `sc_pit_opportunity`, `opponent_undercut`, `opponent_overcut`, `rain_arrival`, `heavy_traffic`, `telemetry_corruption`,
  `missing_telemetry`, `strategy_inferiority`, `driver_disagreement`), verifying deterministic scenario factory creation and
  full end-to-end `ScenarioRunner` execution through the complete normalization, state estimation, opponent intelligence,
  strategy, event detection, and disagreement pipeline.

## What's intentionally NOT claimed

- No claim of real F1 telemetry access or FIA integration.
- No claim of production readiness.
- No claim that any predictive model outperforms a naive baseline until
  Phase 20 (backtesting) actually measures it. If it doesn't, that will be
  reported here plainly, not hidden.

This section grows as each phase lands; see [docs/PROGRESS.md](PROGRESS.md)
for phase-by-phase status and [docs/MODELS.md](MODELS.md) for per-model
validation methodology once models exist.
