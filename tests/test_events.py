"""Tests for backend/events/model.py and detector.py."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.events.detector import DetectionThresholds, EventDetectionEngine
from backend.events.model import DETECTOR_STATUS, EventType
from backend.state.baseline import BaselineTrajectory
from backend.state.race_state import RaceState
from backend.weather.model import WeatherAssessment

BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _state(**overrides) -> RaceState:
    state = RaceState(car_id="44", current_lap=5, last_updated=BASE_TS)
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


def test_detector_status_covers_every_event_type():
    assert set(DETECTOR_STATUS.keys()) == set(EventType)


def test_safety_car_fires_once_on_rising_edge_not_while_held():
    engine = EventDetectionEngine()
    state = _state(safety_car=False)

    assert engine.detect(state) == []

    state.safety_car = True
    first = engine.detect(state)
    assert len(first) == 1
    assert first[0].event_type == EventType.SAFETY_CAR
    assert first[0].severity.value == "CRITICAL"

    # still true on the next frame -- must not re-fire
    assert engine.detect(state) == []

    # drops, then rises again -- must fire again
    state.safety_car = False
    assert engine.detect(state) == []
    state.safety_car = True
    second = engine.detect(state)
    assert len(second) == 1


def test_vsc_fires_on_rising_edge():
    engine = EventDetectionEngine()
    state = _state(vsc=True)
    events = engine.detect(state)
    assert len(events) == 1
    assert events[0].event_type == EventType.VSC
    assert engine.detect(state) == []


def test_tyre_cliff_approaching_fires_when_crossing_threshold():
    engine = EventDetectionEngine(DetectionThresholds(tyre_cliff_probability=0.4))
    state = _state(tyre_cliff_probability=0.1)
    assert engine.detect(state) == []

    state.tyre_cliff_probability = 0.55
    events = engine.detect(state)
    assert len(events) == 1
    assert events[0].event_type == EventType.TYRE_CLIFF_APPROACHING
    assert events[0].confidence == 0.55

    assert engine.detect(state) == []  # held above threshold -- no re-fire


def test_degradation_accelerating_fires_when_crossing_threshold():
    engine = EventDetectionEngine(DetectionThresholds(degradation_acceleration_s_per_lap2=0.02))
    state = _state(degradation_acceleration_s_per_lap2=0.005)
    assert engine.detect(state) == []

    state.degradation_acceleration_s_per_lap2 = 0.05
    events = engine.detect(state)
    assert len(events) == 1
    assert events[0].event_type == EventType.TYRE_DEGRADATION_ACCELERATING


def test_pace_drop_edge_triggers_and_does_not_spam_within_the_same_lap():
    """Regression test: PACE_DROP must not re-fire on every detect() call
    while pace_delta_s stays constant across many frames within one lap --
    an earlier version of this detector had no edge-triggering here at all."""

    engine = EventDetectionEngine(DetectionThresholds(pace_drop_s=0.5))
    state = _state(pace_delta_s=1.2, current_pace_s=91.5)

    first_call = engine.detect(state)
    assert len(first_call) == 1
    assert first_call[0].event_type == EventType.PACE_DROP

    # Simulate several more frames within the same lap: pace_delta_s unchanged.
    for _ in range(5):
        assert engine.detect(state) == []


def test_pace_drop_does_not_fire_below_threshold():
    engine = EventDetectionEngine(DetectionThresholds(pace_drop_s=0.5))
    state = _state(pace_delta_s=0.1)
    assert engine.detect(state) == []


def test_free_pit_window_fires_on_entering_window_not_while_inside():
    engine = EventDetectionEngine()
    trajectory = BaselineTrajectory(generated_at_lap=5, horizon_laps=10, recommended_pit_window=(6, 8))
    state = _state(current_lap=5, baseline_trajectory=trajectory)
    assert engine.detect(state) == []

    state.current_lap = 6
    events = engine.detect(state)
    assert len(events) == 1
    assert events[0].event_type == EventType.FREE_PIT_WINDOW

    state.current_lap = 7
    assert engine.detect(state) == []  # still inside window -- no re-fire


def _wx(trend, transitioning, confidence=0.8):
    return WeatherAssessment(car_id="44", lap=5, weather=None, rain_probability=0.4, trend_per_lap=trend, transitioning=transitioning, confidence=confidence)


def test_rain_incoming_fires_on_wetting_trend_rising_edge():
    engine = EventDetectionEngine()
    state = _state()

    assert engine.detect(state, weather_assessment=_wx(trend=0.1, transitioning=True)) != []
    events = engine.recent_events("44")
    assert len(events) == 1
    assert events[0].event_type == EventType.RAIN_INCOMING

    # held steady -- no re-fire
    assert engine.detect(state, weather_assessment=_wx(trend=0.1, transitioning=True)) == []


def test_rain_incoming_does_not_fire_for_drying_trend():
    engine = EventDetectionEngine()
    state = _state()
    assert engine.detect(state, weather_assessment=_wx(trend=-0.1, transitioning=True)) == []


def test_rain_incoming_does_not_fire_when_not_transitioning():
    engine = EventDetectionEngine()
    state = _state()
    assert engine.detect(state, weather_assessment=_wx(trend=0.01, transitioning=False)) == []


def test_rain_incoming_handles_missing_weather_assessment_gracefully():
    engine = EventDetectionEngine()
    state = _state()
    assert engine.detect(state) == []  # no weather_assessment passed at all


def test_recent_events_accumulates_and_is_bounded():
    engine = EventDetectionEngine(history_size=2)
    state = _state(safety_car=False, vsc=False)

    state.safety_car = True
    engine.detect(state)
    state.safety_car = False
    state.vsc = True
    engine.detect(state)
    state.vsc = False
    state.safety_car = True
    engine.detect(state)

    history = engine.recent_events("44")
    assert len(history) == 2  # bounded to history_size


def test_separate_memory_per_car():
    engine = EventDetectionEngine()
    state_a = _state()
    state_a.car_id = "44"
    state_a.safety_car = True
    state_b = _state()
    state_b.car_id = "1"
    state_b.safety_car = False

    events_a = engine.detect(state_a)
    events_b = engine.detect(state_b)

    assert len(events_a) == 1
    assert events_b == []
