"""Tests for Phase 15 -- Racing Line Intelligence (`backend/racing_line`)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.events.detector import EventDetectionEngine
from backend.events.model import EventType
from backend.racing_line.estimator import RacingLineEstimator
from backend.racing_line.model import (
    CornerAnalysis,
    LineClassification,
    RacingLineAnalysis,
    analyze_lap_racing_line,
)
from backend.state.race_state import RaceState
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig
from simulator.generator.track import default_track

BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_analyze_lap_racing_line_returns_analysis_for_all_corners():
    config = GeneratorConfig(laps=2, noise=NoiseConfig.clean())
    frames = list(TelemetryGenerator(config, seed=1).frames())
    lap1_frames = [f for f in frames if f.lap == 1]

    analysis = analyze_lap_racing_line(car_id="44", lap=1, frames=lap1_frames)

    assert analysis.car_id == "44"
    assert analysis.lap == 1
    assert len(analysis.corner_analyses) == 14
    assert analysis.total_time_loss_s >= 0.0
    assert isinstance(analysis.overall_classification, LineClassification)

    corner1 = analysis.corner_analyses[0]
    assert corner1.corner_number == 1
    assert corner1.corner_name == "Turn 1"
    assert corner1.apex_speed_kph > 0.0
    assert corner1.entry_speed_kph > 0.0
    assert corner1.exit_speed_kph > 0.0


def test_line_classification_ideal():
    config = GeneratorConfig(laps=2, noise=NoiseConfig.clean())
    frames = list(TelemetryGenerator(config, seed=2).frames())
    lap1_frames = [f for f in frames if f.lap == 1]

    analysis = analyze_lap_racing_line(car_id="44", lap=1, frames=lap1_frames)
    assert analysis.overall_classification in (LineClassification.IDEAL, LineClassification.ATTACKING, LineClassification.DEFENSIVE)


def test_estimator_updates_state_and_tracks_laps():
    config = GeneratorConfig(laps=3, noise=NoiseConfig.clean())
    generator = TelemetryGenerator(config, seed=3)
    frames = list(generator.frames())

    estimator = RacingLineEstimator()
    state = RaceState(car_id="44", current_lap=1)

    for frame in frames:
        estimator.process_frame(frame)

    state.completed_laps.append(
        type("LapRecordMock", (), {"lap": 1, "lap_time_s": 105.0})()
    )
    state.completed_laps.append(
        type("LapRecordMock", (), {"lap": 2, "lap_time_s": 106.0})()
    )

    analysis = estimator.update(state)

    assert analysis is not None
    assert state.racing_line_analysis is not None
    assert state.racing_line_analysis.lap == 2
    assert len(state.racing_line_analysis.corner_analyses) == 14


def test_racing_line_degradation_event_firing():
    engine = EventDetectionEngine()
    state = RaceState(car_id="44", current_lap=5, last_updated=BASE_TS)

    # Initial state without racing line degradation
    state.racing_line_analysis = RacingLineAnalysis(
        car_id="44",
        lap=5,
        total_time_loss_s=0.1,
        line_degradation_detected=False,
    )
    events = engine.detect(state)
    assert events == []

    # State with racing line degradation
    state.racing_line_analysis = RacingLineAnalysis(
        car_id="44",
        lap=5,
        total_time_loss_s=0.6,
        line_degradation_detected=True,
    )
    events = engine.detect(state)
    assert len(events) == 1
    assert events[0].event_type == EventType.RACING_LINE_DEGRADATION
    assert events[0].evidence["total_time_loss_s"] == 0.6

    # Subsequent call with same condition -- no re-fire
    assert engine.detect(state) == []
