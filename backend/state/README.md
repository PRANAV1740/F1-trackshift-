# backend/state

**Status: implemented (Phase 4).**

`race_state.py::RaceState` is the continuously-updated per-car state every
intelligence module reads from and writes into — see the field-level
"populated by Phase N" comments in the dataclass itself for which fields
are real today versus reserved placeholders for tyre/pace/opponent/
strategy/prediction/baseline-trajectory intelligence that doesn't exist
yet.

`estimator.py::RaceStateEstimator` builds it from a stream of
`NormalizationResult`s (Phase 3's output) — designed to be plugged straight
into `IngestionService` as a sink (`service.add_sink(estimator.update)`,
see backend/ingestion/service.py). Every update touches only the fields
that changed (O(1) per frame); the one place history matters is lap-
boundary detection, which only needs the previous frame's lap number
(already on the state) — there is no full recompute over history per frame,
per the Phase 4 requirement.

Lap completion produces a `LapRecord` (raw observed lap time + tyre state
at the time), which is the raw input `backend/pace` and `backend/tyre`
decompose into effects (Phases 5-6) — this state does not itself attempt
that decomposition.

**`baseline.py` / `baseline_estimator.py` (Phase 7).** The continuously-
updated baseline trajectory: "if current conditions continue, what
happens?" Future pace/tyre-state projection and a recommended pit window
are genuine, built on Phase 5/6's fitted models; position/gap/finish-
outcome are an explicitly-labeled **naive** carry-forward of current
values (`BaselineTrajectory.method_note`), since a real forecast needs
Phase 11 (position prediction) and Phase 14 (opponents), neither built
yet. One continuously-maintained baseline, recomputed on lap completion —
not a multi-scenario/counterfactual simulation.
