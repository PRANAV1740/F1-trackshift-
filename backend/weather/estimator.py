"""`WeatherIntelligenceEstimator`: tracks per-car rain-probability history
and produces a `WeatherAssessment` (including the wetting/drying trend)
each time `RaceState` updates. Cheap: appends at most one point per lap to
a bounded history, then a single linear regression over that history.
"""

from __future__ import annotations

from collections import defaultdict

from backend.state.race_state import RaceState
from backend.weather.model import WeatherAssessment, assess_weather


class WeatherIntelligenceEstimator:
    def __init__(self, history_size: int = 15):
        self._history: dict[str, list[tuple[int, float]]] = defaultdict(list)
        self._history_size = history_size

    def update(self, state: RaceState) -> WeatherAssessment:
        rain_probability = state.rain_probability if state.rain_probability is not None else 0.0
        history = self._history[state.car_id]
        if not history or history[-1][0] != state.current_lap:
            history.append((state.current_lap, rain_probability))
            if len(history) > self._history_size:
                del history[0]

        return assess_weather(state.car_id, state.current_lap, state.weather, rain_probability, history)
