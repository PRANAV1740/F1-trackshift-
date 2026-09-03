"""`StrategyEngineEstimator`: wires `backend/strategy/engine.py` into `RaceState`.

Reassessment triggers on lap completion (like the other estimators) OR on
a change to the safety-car/VSC flags -- the latter is what makes this
"event-driven" in the sense Phase 8 asks for: a safety car deployment must
prompt an immediate reassessment, not wait for the current lap to finish.
Full event-driven reassessment (any CRITICAL/WARNING event from
`backend/events` triggering it) is a natural extension once an orchestrator
exists to wire `EventDetectionEngine`'s output in; SC/VSC are handled
directly here because they're both detectable today and directly change
the pit-loss term in the objective, so reacting to them immediately is
cheap and clearly correct without waiting on that wiring.
"""

from __future__ import annotations

from backend.pace.estimator import PaceIntelligenceEstimator
from backend.state.race_state import RaceState
from backend.strategy.engine import StrategyConfig, StrategyDecision, decide
from backend.tyre.estimator import TyreDegradationEstimator


class StrategyEngineEstimator:
    def __init__(self, config: StrategyConfig = StrategyConfig()):
        self._config = config
        self._seen_lap_count: dict[str, int] = {}
        self._last_flags: dict[str, tuple[bool, bool]] = {}

    def update(
        self,
        state: RaceState,
        tyre_estimator: TyreDegradationEstimator,
        pace_estimator: PaceIntelligenceEstimator | None = None,
        force: bool = False,
    ) -> StrategyDecision:
        car_id = state.car_id
        seen_laps = self._seen_lap_count.get(car_id, -1)
        prev_flags = self._last_flags.get(car_id, (False, False))
        current_flags = (state.safety_car, state.vsc)

        lap_changed = len(state.completed_laps) != seen_laps
        flags_changed = current_flags != prev_flags

        if force or lap_changed or flags_changed or state.current_strategy is None:
            state.current_strategy = decide(state, tyre_estimator, pace_estimator, self._config)
            self._seen_lap_count[car_id] = len(state.completed_laps)
            self._last_flags[car_id] = current_flags

        return state.current_strategy
