# backend/pace

**Status: implemented (Phase 6).**

`model.py::estimate_pace` reports, together and inspectably: current pace
(most recent lap, whatever its condition), expected clean pace (from
Phase 5's fitted degradation curve evaluated at current age/fuel/lap when
available, else a rolling average of recent clean laps as a labeled
fallback), the delta between them, and a short-window trend slope. Never
returns a single opaque "pace" number.

`estimator.py::PaceIntelligenceEstimator` wires it into `RaceState`, same
event-driven shape as `backend/tyre/estimator.py` (recomputes only on lap
completion).

`LapRecord.is_clean()` (on `backend/state/race_state.py`) is the shared
"is this lap usable" predicate — used by both this module and
`backend/tyre`, so the two don't duplicate or drift on what counts as a
clean lap.
