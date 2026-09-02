# backend/tyre

**Status: implemented (Phase 5).** This is the official TrackShift 2026
problem statement.

`model.py` decomposes lap time into base pace + assumed fuel effect +
assumed track evolution + degradation + noise, and fits only the
degradation curve (linear + grid-searched cliff breakpoint) via weighted
least squares — deliberately not `lap_time_delta == degradation`. Full
rationale, the identifiability argument for why fuel/evolution are assumed
rather than fit, and documented limitations are in the module docstring and
[docs/MODELS.md](../../docs/MODELS.md).

`estimator.py::TyreDegradationEstimator` wires the model into `RaceState`:
cheap to call after every frame, refits only when a car's
`completed_laps` has grown (event-driven, not per-tick), filtering out
pit/non-green/low-confidence laps before fitting.

See [docs/VALIDATION.md](../../docs/VALIDATION.md) for the actual recovery
numbers against known synthetic ground truth (`tests/test_tyre_model.py`).
