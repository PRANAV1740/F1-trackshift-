# backend/strategy

**Status: implemented (Phase 9).**

`engine.py::decide()` is the only place PIT/STAY_OUT gets decided — a pure
function scoring every candidate against an explicit objective function
(`objective.py`, math fully written out in [docs/STRATEGY.md](../../docs/STRATEGY.md)):
projected stint time (reusing `backend/pace`'s pace projection over the
same remaining-race-distance horizon for every candidate) + a residual-
uncertainty risk penalty + a cliff-probability/unfitted-curve failure
penalty. VSC/SC-aware pit-loss reduction is one term in that same
function, not a bolt-on. `estimator.py::StrategyEngineEstimator` wires it
into `RaceState.current_strategy`, reassessing on lap completion or an
SC/VSC flag change.

`StrategyDecisionType` declares the full vocabulary (`PIT`, `STAY_OUT`,
`PIT_NEXT_LAP`, `EXTEND`, `UNDERCUT`, `OVERCUT`, `ATTACK`, `DEFEND`), but
the last four are never selected yet — they need Phase 14's opponent
intelligence. `expected_position`/`position_gain` are an explicitly-flagged
naive carry-forward pending Phase 11/14.

A real off-by-one-lap bug in the objective's horizon accounting was found
and fixed during this phase's own test-writing — see
[docs/VALIDATION.md](../../docs/VALIDATION.md) for the account.
