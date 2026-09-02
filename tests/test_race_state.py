"""Tests for backend/state/estimator.py and race_state.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.normalization.base import NormalizationResult
from backend.normalization.stages import default_pipeline
from backend.state.estimator import RaceStateEstimator
from backend.telemetry.schema import DataSource, PitStatus, PitStop, RaceTelemetry
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig

BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _frame(**overrides) -> RaceTelemetry:
    defaults = dict(source=DataSource.SIMULATOR, source_timestamp=BASE_TS, car_id="44", lap=1)
    defaults.update(overrides)
    return RaceTelemetry(**defaults)


def _result(frame) -> NormalizationResult:
    return NormalizationResult(raw_frame=frame, normalized_frame=frame, issues=[], changes=[])


def test_first_frame_creates_state_with_expected_fields():
    estimator = RaceStateEstimator()
    frame = _frame(position=3, speed_kph=280.0, tyre_age_laps=2)

    state = estimator.update(_result(frame))

    assert state.car_id == "44"
    assert state.current_lap == 1
    assert state.position == 3
    assert state.current_speed_kph == 280.0
    assert state.version == 1


def test_state_updates_incrementally_across_frames_same_lap():
    estimator = RaceStateEstimator()
    estimator.update(_result(_frame(speed_kph=200.0, sequence_id=1)))
    state = estimator.update(_result(_frame(speed_kph=210.0, sequence_id=2)))

    assert state.current_speed_kph == 210.0
    assert state.version == 2
    assert state.completed_laps == []


def test_lap_boundary_finalizes_a_lap_record():
    estimator = RaceStateEstimator()
    estimator.update(_result(_frame(lap=1, source_timestamp=BASE_TS, tyre_age_laps=0)))
    estimator.update(_result(_frame(lap=1, source_timestamp=BASE_TS + timedelta(seconds=45), tyre_age_laps=0)))
    state = estimator.update(
        _result(_frame(lap=2, source_timestamp=BASE_TS + timedelta(seconds=91), tyre_age_laps=1))
    )

    assert state.current_lap == 2
    assert len(state.completed_laps) == 1
    lap_record = state.completed_laps[0]
    assert lap_record.lap == 1
    assert lap_record.lap_time_s == pytest.approx(91.0)
    assert lap_record.tyre_age_laps == 0


def test_dropped_frame_is_a_safe_no_op():
    estimator = RaceStateEstimator()
    dropped = NormalizationResult(raw_frame=_frame(), normalized_frame=None, issues=[], changes=[], dropped_at_stage="x")

    result = estimator.update(dropped)

    assert result is None
    assert estimator.all_states() == {}


def test_separate_states_per_car():
    estimator = RaceStateEstimator()
    estimator.update(_result(_frame(car_id="44", position=1)))
    estimator.update(_result(_frame(car_id="1", position=2)))

    assert estimator.get_state("44").position == 1
    assert estimator.get_state("1").position == 2
    assert len(estimator.all_states()) == 2


def test_pit_history_accumulates_without_duplicates():
    estimator = RaceStateEstimator()
    stop = PitStop(lap=10)
    estimator.update(_result(_frame(pit_history=[stop])))
    state = estimator.update(_result(_frame(pit_history=[stop])))

    assert len(state.pit_history) == 1


def test_confidence_reflects_latest_sensor_confidence():
    estimator = RaceStateEstimator()
    config = GeneratorConfig(laps=1, noise=NoiseConfig.clean())
    frame = list(TelemetryGenerator(config, seed=1).frames())[0]
    result = default_pipeline().process(frame)

    state = estimator.update(result)

    assert 0.0 <= state.confidence <= 1.0
    assert state.confidence == result.normalized_frame.sensor_confidence.overall


def test_end_to_end_two_lap_simulation_produces_sane_state():
    config = GeneratorConfig(laps=2, noise=NoiseConfig.moderate())
    frames = list(TelemetryGenerator(config, seed=7).frames())

    pipeline = default_pipeline()
    estimator = RaceStateEstimator()
    final_state = None
    for frame in frames:
        result = pipeline.process(frame)
        updated = estimator.update(result)
        if updated is not None:
            final_state = updated

    assert final_state is not None
    assert final_state.current_lap == 2
    assert final_state.tyre_age_laps == 1
    assert len(final_state.completed_laps) == 1

    lap1 = final_state.completed_laps[0]
    assert lap1.lap == 1
    assert lap1.lap_time_s is not None and 60.0 < lap1.lap_time_s < 200.0
    assert 0.0 <= lap1.avg_confidence <= 1.0
