"""Tests for backend/weather/model.py and estimator.py."""

from __future__ import annotations

from backend.state.race_state import RaceState
from backend.telemetry.schema import WeatherState
from backend.weather.estimator import WeatherIntelligenceEstimator
from backend.weather.model import assess_weather


def test_no_history_gives_no_trend():
    assessment = assess_weather("44", lap=1, current_weather=WeatherState.DRY, current_rain_probability=0.0, history=[])
    assert assessment.trend_per_lap is None
    assert assessment.transitioning is False


def test_rising_rain_probability_detected_as_wetting_trend():
    history = [(1, 0.0), (2, 0.1), (3, 0.25), (4, 0.4)]
    assessment = assess_weather("44", lap=4, current_weather=WeatherState.DAMP, current_rain_probability=0.4, history=history)

    assert assessment.trend_per_lap is not None
    assert assessment.trend_per_lap > 0
    assert assessment.transitioning is True


def test_falling_rain_probability_detected_as_drying_trend():
    history = [(1, 0.6), (2, 0.4), (3, 0.2), (4, 0.05)]
    assessment = assess_weather("44", lap=4, current_weather=WeatherState.DAMP, current_rain_probability=0.05, history=history)

    assert assessment.trend_per_lap is not None
    assert assessment.trend_per_lap < 0
    assert assessment.transitioning is True


def test_stable_rain_probability_is_not_transitioning():
    history = [(1, 0.0), (2, 0.0), (3, 0.01), (4, 0.0)]
    assessment = assess_weather("44", lap=4, current_weather=WeatherState.DRY, current_rain_probability=0.0, history=history)
    assert assessment.transitioning is False


def test_confidence_grows_with_history_length():
    short = assess_weather("44", 3, WeatherState.DRY, 0.0, [(1, 0.0), (2, 0.0), (3, 0.0)])
    long_history = [(i, 0.0) for i in range(1, 11)]
    long_ = assess_weather("44", 10, WeatherState.DRY, 0.0, long_history)
    assert long_.confidence > short.confidence


def test_estimator_builds_history_incrementally():
    estimator = WeatherIntelligenceEstimator()
    state = RaceState(car_id="44", current_lap=1, weather=WeatherState.DRY, rain_probability=0.0)

    estimator.update(state)
    state.current_lap = 2
    state.rain_probability = 0.2
    estimator.update(state)
    state.current_lap = 3
    state.rain_probability = 0.5
    assessment = estimator.update(state)

    assert assessment.trend_per_lap is not None
    assert assessment.trend_per_lap > 0


def test_estimator_does_not_duplicate_same_lap_observations():
    estimator = WeatherIntelligenceEstimator()
    state = RaceState(car_id="44", current_lap=5, rain_probability=0.3)

    estimator.update(state)
    estimator.update(state)  # same lap, called again (e.g. multiple frames within the lap)

    assert len(estimator._history["44"]) == 1
