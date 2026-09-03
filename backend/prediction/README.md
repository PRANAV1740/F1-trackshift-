# backend/prediction

**Status: implemented (Phase 11), honestly gated on opponent data.**

`model.py::predict_position` is a genuine Monte Carlo position-outcome
model: sample this car's and every opponent's projected remaining-race-time
distribution many times, rank each draw, and report the empirical
probability of finishing in each position — not a hand-picked percentage.
Validated in `tests/test_prediction_model.py` with synthetic multi-
opponent fixtures (a dominant car wins P1 with >95% probability, a close
field spreads probability across multiple positions, probabilities sum to
1.0, `expected_position` matches the probability-weighted average).

`estimator.py::PositionPredictionEstimator` wires it into
`RaceState.predicted_finishing_position`, building this car's own time
distribution from `backend/strategy`'s chosen candidate
(`StrategyDecision.chosen_projected_time_s` /
`chosen_residual_std_s × sqrt(chosen_remaining_laps)`). **Opponent
distributions have no live source yet** — the simulator is still
single-car (Phase 2/18) and there is no opponent pace model (Phase 14) —
so live usage today always reports `source="insufficient_opponent_data"`
rather than fabricating a plausible-looking distribution from nothing. The
estimator accepts an injectable `opponent_source` callable so Phase 14
only has to supply real data, not change this wiring.
