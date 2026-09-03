"""Bridges opponent intelligence into `backend/prediction`'s Monte Carlo model.

`PositionPredictionEstimator` (Phase 11) always returned
`source="insufficient_opponent_data"` because nothing supplied real
opponent `TimeDistribution`s. Now that Phase 14 tracks every car's own
fitted degradation curve (all per-car estimators are keyed by `car_id`,
so an "opponent's" curve is just another entry in the same
`TyreDegradationEstimator`), this module builds those distributions the
same way `backend/strategy/objective.py` builds one for the car the
decision is being made for -- reusing `project_pace_curve` rather than
re-deriving the projection math.
"""

from __future__ import annotations

from typing import Optional

from backend.pace.model import project_pace_curve
from backend.prediction.model import TimeDistribution
from backend.state.baseline import estimate_fuel_burn_rate
from backend.state.race_state import RaceState
from backend.tyre.estimator import TyreDegradationEstimator


def build_opponent_time_distribution(
    opponent: RaceState, tyre_estimator: TyreDegradationEstimator, remaining_laps: int
) -> Optional[TimeDistribution]:
    if opponent.tyre_compound is None or opponent.tyre_age_laps is None or remaining_laps <= 0:
        return None
    estimate = tyre_estimator.get_estimate(opponent.car_id, opponent.tyre_compound)
    if estimate is None:
        return None

    fuel = opponent.fuel_load_kg or 0.0
    fuel_burn_rate = estimate_fuel_burn_rate(opponent)
    curve = project_pace_curve(estimate.base_pace_s, estimate, opponent.current_lap, opponent.tyre_age_laps, fuel, fuel_burn_rate, remaining_laps)
    total = sum(p for p in curve if p is not None)
    std = estimate.residual_std_s * (remaining_laps**0.5)
    return TimeDistribution(car_id=opponent.car_id, mean_s=total, std_s=std)


def opponent_distributions_for(
    own_car_id: str,
    all_states: dict[str, RaceState],
    tyre_estimator: TyreDegradationEstimator,
    remaining_laps: int,
) -> list[TimeDistribution]:
    distributions = []
    for car_id, state in all_states.items():
        if car_id == own_car_id:
            continue
        dist = build_opponent_time_distribution(state, tyre_estimator, remaining_laps)
        if dist is not None:
            distributions.append(dist)
    return distributions
