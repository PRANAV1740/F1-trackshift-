# backend/opponents

**Status: implemented (Phase 14).** The first genuinely multi-car
capability in this project — everything before this phase ran one
`SimulatorAdapter` at a time.

- **`order.py::RaceOrderTracker`** — the only genuinely multi-car
  computation needed: position and gap. Everything else about an opponent
  (compound, tyre age, pace, degradation) is already computed per-car by
  Phases 4–6, since every estimator (`RaceStateEstimator`,
  `TyreDegradationEstimator`, `PaceIntelligenceEstimator`) is keyed by
  `car_id` — an "opponent's" state is just another entry in the same dict.
  Position/gap are estimated from each car's lap-progress fraction
  (elapsed time since its current lap started, divided by its own current
  expected lap time), a documented approximation (not timing-loop
  precision) given the schema's 3-way sector resolution.
- **`model.py`** — `pit_probability()` (reuses Phase 5's cliff/remaining-
  life numbers as a probability), `OpponentSummary` (per-opponent view:
  position/compound/age/pace/degradation read straight off their `RaceState`,
  plus `pit_probability`, `undercut_threat`/`overcut_threat`), and
  `classify_pit_timing_opportunity()` — the shared undercut/overcut
  classifier used by both `backend/events`' `UNDERCUT_OPPORTUNITY`/
  `OVERCUT_OPPORTUNITY` detectors and `backend/strategy`'s UNDERCUT/OVERCUT
  relabeling, so the two never disagree. **Documented heuristic, not a
  fitted model** — fixed, named, inspectable thresholds, not calibrated
  against outcome data (there's no multi-race dataset to calibrate
  against in this prototype).
- **`estimator.py::OpponentIntelligenceEstimator`** — the one estimator in
  this project that is NOT single-car: `update_all()` takes the whole
  `RaceStateEstimator` and recomputes order, gaps, and every car's
  opponent summaries together in one pass.
- **`prediction.py`** — bridges opponent data into Phase 11's Monte Carlo
  position model, finally unlocking `source="monte_carlo"` results now
  that real opponent time distributions exist (see
  `backend/prediction/README.md`).

**Two real, significant bugs were found and fixed while building this
phase's end-to-end test** — see `docs/VALIDATION.md` for the full account:

1. Running multiple `SimulatorAdapter`s concurrently in non-realtime mode
   had no yield point in the common case, so `asyncio.gather` let one
   adapter's task monopolize the event loop and run to near-completion
   before its siblings got any turn — a scheduling artifact that looked
   exactly like an unintended pace advantage. Fixed with an unconditional
   `await asyncio.sleep(0)` per frame in non-realtime mode
   (`backend/adapters/simulator_adapter.py`).
2. `RaceOrderTracker` compared `current_lap_start_ts` (always derived from
   `source_timestamp`, the simulated clock) against `ingest_timestamp`
   (real wall-clock time) — the same class of time-domain mismatch bug
   already fixed once in Phase 2, recurring because it wasn't front-of-mind
   when writing new timestamp-comparing code. Produced an elapsed time of
   ~244 *days*. Fixed to compare `source_timestamp` against
   `source_timestamp`.
