"""`PaceIntelligenceEstimator`: wires `backend/pace/model.py` into `RaceState`.

Same event-driven shape as `backend/tyre/estimator.py` and
`backend/state/estimator.py`: cheap to call every frame, recomputes only
when `state.completed_laps` has grown.
"""

from __future__ import annotations

from typing import Optional

from backend.pace.model import PaceEstimate, estimate_pace
from backend.state.race_state import RaceState
from backend.tyre.estimator import TyreDegradationEstimator


class PaceIntelligenceEstimator:
    def __init__(self):
        self._seen_lap_count: dict[str, int] = {}
        self._last_estimate: dict[str, PaceEstimate] = {}

    def get_estimate(self, car_id: str) -> Optional[PaceEstimate]:
        return self._last_estimate.get(car_id)

    def update(self, state: RaceState, tyre_estimator: Optional[TyreDegradationEstimator] = None) -> Optional[PaceEstimate]:
        seen = self._seen_lap_count.get(state.car_id, -1)
        if len(state.completed_laps) != seen or state.car_id not in self._last_estimate:
            self._seen_lap_count[state.car_id] = len(state.completed_laps)

            degradation_estimate = None
            if tyre_estimator is not None and state.tyre_compound is not None:
                degradation_estimate = tyre_estimator.get_estimate(state.car_id, state.tyre_compound)

            estimate = estimate_pace(
                completed_laps=state.completed_laps,
                current_lap=state.current_lap,
                current_tyre_age_laps=state.tyre_age_laps,
                current_fuel_load_kg=state.fuel_load_kg,
                degradation_estimate=degradation_estimate,
            )
            self._last_estimate[state.car_id] = estimate

        estimate = self._last_estimate[state.car_id]
        state.current_pace_s = estimate.current_pace_s
        state.expected_clean_pace_s = estimate.expected_clean_pace_s
        state.pace_delta_s = estimate.pace_delta_s
        state.pace_trend_s_per_lap = estimate.pace_trend_s_per_lap
        return estimate
