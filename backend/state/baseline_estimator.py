"""`BaselineTrajectoryEstimator`: wires `backend/state/baseline.py` into `RaceState`.

Same event-driven shape as the tyre/pace estimators: recomputes only on
lap completion, writes the result onto `state.baseline_trajectory`.
"""

from __future__ import annotations

from typing import Optional

from backend.pace.estimator import PaceIntelligenceEstimator
from backend.state.baseline import BaselineTrajectory, build_baseline_trajectory
from backend.state.race_state import RaceState
from backend.tyre.estimator import TyreDegradationEstimator


class BaselineTrajectoryEstimator:
    def __init__(self, horizon_laps: int = 10):
        self._horizon_laps = horizon_laps
        self._seen_lap_count: dict[str, int] = {}

    def update(
        self,
        state: RaceState,
        tyre_estimator: Optional[TyreDegradationEstimator] = None,
        pace_estimator: Optional[PaceIntelligenceEstimator] = None,
    ) -> Optional[BaselineTrajectory]:
        seen = self._seen_lap_count.get(state.car_id, -1)
        if len(state.completed_laps) == seen and state.baseline_trajectory is not None:
            return state.baseline_trajectory
        self._seen_lap_count[state.car_id] = len(state.completed_laps)

        degradation_estimate = None
        if tyre_estimator is not None and state.tyre_compound is not None:
            degradation_estimate = tyre_estimator.get_estimate(state.car_id, state.tyre_compound)

        pace_estimate = pace_estimator.get_estimate(state.car_id) if pace_estimator is not None else None

        trajectory = build_baseline_trajectory(
            state=state,
            degradation_estimate=degradation_estimate,
            pace_estimate=pace_estimate,
            horizon_laps=self._horizon_laps,
        )
        state.baseline_trajectory = trajectory
        return trajectory
