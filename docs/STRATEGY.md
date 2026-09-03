# Strategy Engine

`backend/strategy/engine.py::decide()` is the **only** place in this
repository that decides PIT vs. STAY_OUT. It is a pure function: given a
`RaceState` and the fitted estimates available for it, it scores every
candidate action and returns a `StrategyDecision`. No LLM, no black box —
every number in the decision traces back to the objective function below.

## The objective function

For every candidate action `c` (stay out, or pit onto a specific compound):

```
score(c) = projected_stint_time_s(c) + risk_penalty_s(c) + failure_penalty_s(c)
```

Lower score wins. This is the "expected [race] time + risk penalty +
failure probability penalty" pattern from the problem statement,
instantiated concretely:

### `projected_stint_time_s(c)`

Sum of per-lap projected pace over the **same remaining-race-distance
horizon** for every candidate (`backend/pace/model.py::project_pace_curve`,
shared with `backend/state/baseline.py`'s own forward projection so the two
never duplicate this loop):

```
projected_pace(lap) = base_pace_s
                     + assumed_fuel_effect_s(fuel_at(lap))
                     + assumed_track_evolution_gain_s(lap)
                     + degradation_estimate.degradation_at(age_at(lap))
```

summed over `remaining_laps = race_total_laps - current_lap` laps. A PIT
candidate additionally adds `pit_loss_s` and restarts tyre age at 0.
**Both STAY_OUT and every PIT candidate are integrated over the identical
`remaining_laps` horizon** — pitting does not skip a lap of race distance;
`pit_loss_s` is the *additional* time the stop itself costs, layered on
top. (An earlier version integrated PIT candidates over
`remaining_laps - 1`, which silently made every pit look about one lap's
pace cheaper than it should — see "A real bug, found and fixed" below.)

`pit_loss_s = base_pit_loss_s × multiplier`, where the multiplier is `1.0`
normally, `vsc_pit_loss_multiplier` (default 0.45) under VSC, or
`sc_pit_loss_multiplier` (default 0.30) under a full safety car — this is
the event-aware pit-loss modeling the problem statement asks for (Phase
12), folded directly into the objective rather than bolted on separately,
since it's just one term in the same function.

### `risk_penalty_s(c)`

```
risk_penalty_s = RISK_UNCERTAINTY_WEIGHT × residual_std_s × sqrt(remaining_laps)
```

`residual_std_s` is the fitted curve's own residual standard deviation
(`backend/tyre/model.py`). Uncertainty is scaled by `sqrt(remaining_laps)`
because independent per-lap errors accumulate additively in variance, so
standard deviation over the whole projection scales with the square root
of the horizon — a standard, not ad-hoc, scaling. `RISK_UNCERTAINTY_WEIGHT
= 1.5` (documented constant, not fit from data).

### `failure_penalty_s(c)`

- **Stay-out candidate:** `cliff_probability_within(age_at_horizon_end) ×
  CLIFF_FAILURE_COST_S` (default `CLIFF_FAILURE_COST_S = 8.0`) — the
  posterior probability mass (from `backend/tyre`'s Bayesian-flavored
  cliff posterior) that the tyre's fitted cliff lies at or before the end
  of the comparison horizon, scaled by an assumed cost representing risk
  beyond the smooth quadratic model (a spin, extra unmodeled wear).
- **Pit candidate onto a compound with no fitted curve this session:**
  flat `NO_FITTED_CURVE_PENALTY_S = 3.0` — using
  `objective.fallback_degradation_estimate()` (a documented, qualitative
  compound-stiffness prior, `ASSUMED_COMPOUND_RATE_MULTIPLIER`, scaled from
  whatever curve *is* fitted — never the simulator's own ground truth,
  which this code must never import) is treated as less trustworthy than a
  curve actually fitted from this car's own laps.

## Decision type selection

Given the winning candidate:

- **Wins on pitting:** `PIT_NEXT_LAP` if VSC/SC is active right now, or the
  car's current `tyre_cliff_probability` is at or above
  `pit_next_lap_cliff_probability_threshold` (default 0.6) — otherwise
  `PIT`. `window` is `(current_lap+1, current_lap+1)` when urgent, else
  `backend/state`'s baseline `recommended_pit_window` if one exists, else a
  3-lap default window.
- **Wins on staying out:** `EXTEND` if `remaining_tyre_life_laps` (Phase 5)
  is at least `extend_remaining_life_threshold_laps` (default 5), else
  `STAY_OUT`.
- `UNDERCUT` / `OVERCUT` / `ATTACK` / `DEFEND` remain declared in
  `StrategyDecisionType` (the vocabulary is complete from the start, same
  pattern as `backend/events`) but are **never selected yet** — they need
  opponent-relative reasoning that only exists once Phase 14 (opponent
  intelligence) lands. Extending `decide()` to consider them is Phase 14's
  job, not a rewrite of this one.

## Confidence

```
margin_s = runner_up_score - best_score
confidence = clip(0.5 + min(margin_s / confidence_margin_scale_s, 0.4), 0.05, 0.95)
```

then multiplied by `0.8` if the winning candidate used a fallback
(unfitted) degradation curve, and by `0.9` if its fitted curve has fewer
than 8 observations. `confidence_margin_scale_s` defaults to 8.0 seconds —
a margin of that size or more between the best and second-best candidate
saturates the margin-derived component at its max (0.9 before the
fallback/sample-size discounts). This is a simple, transparent formula, not
a calibrated probability — documented as such, not oversold.

## What's still naive

`expected_position` and `position_gain` are a **naive carry-forward**
(current position, zero gain) — `StrategyDecision.position_forecast_is_naive`
is always `True` today, and every decision's `risks` list states this in
plain language. A real forecast needs Phase 11 (position prediction) and
Phase 14 (opponent intelligence).

## A real bug, found and fixed

The first implementation passed `remaining_laps - 1` to every PIT
candidate's projection ("to avoid double-counting the pit lap"), while
STAY_OUT was projected over the full `remaining_laps`. This silently made
every pit candidate about one lap's pace cheaper than it should have been
— caught by a test asserting that a fresh, healthy tyre with 7 laps left
in the race should stay out; the engine instead recommended pitting onto
an identical fresh tyre, a ~70-second miscalculation traced directly to
the off-by-one horizon. Fixed by integrating every candidate over the
identical horizon (see `backend/strategy/objective.py::score_pit`'s
docstring for the full account). Two other tests in
`tests/test_strategy_engine.py` needed their own numeric assumptions
corrected once the fix landed — see docs/VALIDATION.md for what changed
and why each was a genuine modeling insight rather than a tolerance
adjustment.
