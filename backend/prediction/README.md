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
`chosen_residual_std_s × sqrt(chosen_remaining_laps)`).

**Update (Phase 14): opponent distributions now have a real source.**
`backend/opponents/prediction.py::opponent_distributions_for` builds a
`TimeDistribution` for every other tracked car the same way (via each
car's own fitted degradation curve, since `TyreDegradationEstimator` is
keyed by `car_id`) — proven end-to-end in
`tests/test_opponents_estimator.py`, which asserts `source == "monte_carlo"`
mid-race in a real 3-car simulation. Live usage still reports
`source="insufficient_opponent_data"` whenever `opponent_source` isn't
wired up or genuinely has no data (e.g. a single-car run, or right at race
end when `remaining_laps` hits 0 for every car) — that remains the honest
answer in those cases, not a fallback to be avoided.
