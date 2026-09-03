"""Weather state assessment.

No live weather feed exists or is claimed anywhere in this project
(engineering rule 8) -- `RaceTelemetry.weather`/`rain_probability` is
already the integration point for one: any adapter (a real one, in
principle) populates those two fields exactly like the simulator does, and
everything below consumes only that common schema, never a
weather-specific source. That IS the "clean future integration interface"
the problem statement asks for; there is no separate weather adapter
because the common telemetry schema already carries what weather
intelligence needs.

What this module adds beyond the raw fields: a wetting/drying **trend**,
estimated from the actual recent history of observed `rain_probability`
(simple linear regression, `numpy.polyfit`) rather than the instantaneous
value alone -- the raw value tells you the current state, the trend is
what lets `TRANSITIONING` be detected and fed to Phase 8's
`RAIN_INCOMING` event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from backend.telemetry.schema import WeatherState

MIN_HISTORY_FOR_TREND = 3
DEFAULT_TRANSITION_THRESHOLD_PER_LAP = 0.05


@dataclass
class WeatherAssessment:
    car_id: str
    lap: int
    weather: Optional[WeatherState]
    rain_probability: float
    trend_per_lap: Optional[float]  # positive = wetting, negative = drying
    transitioning: bool
    confidence: float


def assess_weather(
    car_id: str,
    lap: int,
    current_weather: Optional[WeatherState],
    current_rain_probability: float,
    history: list[tuple[int, float]],
    transition_threshold_per_lap: float = DEFAULT_TRANSITION_THRESHOLD_PER_LAP,
) -> WeatherAssessment:
    trend: Optional[float] = None
    if len(history) >= MIN_HISTORY_FOR_TREND:
        laps = np.array([lap_no for lap_no, _ in history], dtype=float)
        probs = np.array([prob for _, prob in history], dtype=float)
        if laps.max() > laps.min():  # polyfit needs more than one distinct x
            slope, _intercept = np.polyfit(laps, probs, 1)
            trend = float(slope)

    transitioning = trend is not None and abs(trend) >= transition_threshold_per_lap
    confidence = min(1.0, len(history) / 10.0)

    return WeatherAssessment(
        car_id=car_id,
        lap=lap,
        weather=current_weather,
        rain_probability=current_rain_probability,
        trend_per_lap=trend,
        transitioning=transitioning,
        confidence=confidence,
    )
