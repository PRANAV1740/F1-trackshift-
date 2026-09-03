"""`PositionPredictionEstimator`: wires `backend/prediction/model.py` into `RaceState`.

`opponent_distributions` has no live source yet -- Phase 14 (opponent
intelligence) is what will translate `RaceState.opponents_last_seen` (raw
snapshots) into genuine `TimeDistribution`s an opponent might actually
achieve. Until then this always resolves to
`source="insufficient_opponent_data"`, honestly, rather than fabricating
distributions from data that doesn't support them. The parameter exists
now so Phase 14 only has to supply data, not change this wiring.
"""

from __future__ import annotations

from typing import Callable, Optional

from backend.prediction.model import PositionPrediction, TimeDistribution, predict_position
from backend.state.race_state import RaceState

OpponentDistributionSource = Callable[[RaceState], list[TimeDistribution]]


class PositionPredictionEstimator:
    def __init__(self, n_simulations: int = 5000, seed: int = 42, opponent_source: Optional[OpponentDistributionSource] = None):
        self._n_simulations = n_simulations
        self._seed = seed
        self._opponent_source = opponent_source
        self._seen_lap_count: dict[str, int] = {}

    def update(self, state: RaceState) -> PositionPrediction:
        seen = self._seen_lap_count.get(state.car_id, -1)
        if len(state.completed_laps) == seen and state.predicted_finishing_position is not None:
            return state.predicted_finishing_position
        self._seen_lap_count[state.car_id] = len(state.completed_laps)

        decision = state.current_strategy
        if (
            decision is None
            or decision.chosen_projected_time_s is None
            or decision.chosen_residual_std_s is None
            or decision.chosen_remaining_laps is None
        ):
            prediction = PositionPrediction(
                car_id=state.car_id,
                lap=state.current_lap,
                source="insufficient_opponent_data",
                note="No strategy decision with a fitted time projection yet.",
            )
        else:
            own = TimeDistribution(
                car_id=state.car_id,
                mean_s=decision.chosen_projected_time_s,
                std_s=decision.chosen_residual_std_s * (decision.chosen_remaining_laps**0.5),
            )
            opponents = self._opponent_source(state) if self._opponent_source else []
            prediction = predict_position(
                own, opponents, state.position or 0, state.current_lap, self._n_simulations, self._seed
            )

        state.predicted_finishing_position = prediction
        return prediction
