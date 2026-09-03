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
`PIT_NEXT_LAP`, `EXTEND`, `UNDERCUT`, `OVERCUT`, `ATTACK`, `DEFEND`).

**Update (Phase 14): `UNDERCUT`/`OVERCUT` are now selected.** When the
objective already favors pitting, `decide()` checks the closest tracked
opponent ahead via the same `classify_pit_timing_opportunity()` classifier
`backend/events` uses for its matching event — if they're close and not
about to react, the decision relabels to `UNDERCUT`; if they're close and
about to pit while we aren't, it relabels to `OVERCUT`. The underlying
pit-now economics are unchanged either way; only the label and reasons are
enriched. `ATTACK`/`DEFEND` remain declared but unselected — those are
on-track racing-line/battle decisions, not pit-timing ones, and belong to
Phase 15 (racing-line intelligence). `expected_position`/`position_gain`
remain an explicitly-flagged naive carry-forward pending Phase 11's full
integration.

A real off-by-one-lap bug in the objective's horizon accounting was found
and fixed during this phase's own test-writing — see
[docs/VALIDATION.md](../../docs/VALIDATION.md) for the account.
