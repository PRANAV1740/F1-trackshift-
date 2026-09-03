"""`OpponentIntelligenceEstimator`: multi-car position/gap tracking plus
per-car opponent summaries.

Unlike every other estimator in this project, this one is NOT keyed to a
single car -- position and gaps are inherently a multi-car computation, so
`update_all()` takes the whole `RaceStateEstimator` (which already holds
every tracked car's `RaceState`, keyed by `car_id` from Phase 4) and
recomputes order, gaps, and every car's opponent summaries together in one
pass.
"""

from __future__ import annotations

from backend.opponents.model import OpponentSummary, summarize_opponent
from backend.opponents.order import RaceOrderTracker
from backend.state.estimator import RaceStateEstimator

MAX_TRACKED_OPPONENTS = 6


class OpponentIntelligenceEstimator:
    def __init__(self, order_tracker: RaceOrderTracker | None = None):
        self._order_tracker = order_tracker or RaceOrderTracker()

    @property
    def order_tracker(self) -> RaceOrderTracker:
        return self._order_tracker

    def update_all(self, race_state_estimator: RaceStateEstimator) -> None:
        all_states = race_state_estimator.all_states()
        if len(all_states) < 2:
            return  # nothing to compare against -- single-car case stays untouched

        for state in all_states.values():
            self._order_tracker.update(state)
        self._order_tracker.apply(all_states)

        for car_id, state in all_states.items():
            summaries: dict[str, OpponentSummary] = {}
            others = sorted(
                (o for o in all_states.values() if o.car_id != car_id),
                key=lambda o: abs((o.position or 0) - (state.position or 0)),
            )
            for opponent in others[:MAX_TRACKED_OPPONENTS]:
                gap = self._order_tracker.gap_seconds(car_id, opponent.car_id)
                is_ahead = gap is not None and gap > 0
                summaries[opponent.car_id] = summarize_opponent(
                    state, opponent, abs(gap) if gap is not None else None, is_ahead
                )
            state.opponent_threats = summaries
