"""Tests for backend/pace/estimator.py -- wiring into RaceState."""

from __future__ import annotations

from backend.normalization.stages import default_pipeline
from backend.pace.estimator import PaceIntelligenceEstimator
from backend.state.estimator import RaceStateEstimator
from backend.tyre.estimator import TyreDegradationEstimator
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig


def _run_stint(seed: int, laps: int, noise: NoiseConfig):
    config = GeneratorConfig(laps=laps, noise=noise)
    frames = list(TelemetryGenerator(config, seed=seed).frames())

    pipeline = default_pipeline()
    race_state_estimator = RaceStateEstimator()
    tyre_estimator = TyreDegradationEstimator()
    pace_estimator = PaceIntelligenceEstimator()

    for frame in frames:
        result = pipeline.process(frame)
        state = race_state_estimator.update(result)
        if state is not None:
            tyre_estimator.update(state)
            pace_estimator.update(state, tyre_estimator=tyre_estimator)

    return race_state_estimator.get_state(config.car_id)


def test_pace_fields_populate_after_first_completed_lap():
    state = _run_stint(seed=1, laps=3, noise=NoiseConfig.clean())

    assert len(state.completed_laps) >= 1
    assert state.current_pace_s is not None
    assert state.expected_clean_pace_s is not None  # rolling-average fallback kicks in from lap 1


def test_pace_switches_to_tyre_model_source_once_enough_laps_exist():
    state = _run_stint(seed=1, laps=12, noise=NoiseConfig.moderate())

    assert state.pace_delta_s is not None
    assert state.pace_trend_s_per_lap is not None


def test_pace_estimator_is_lap_boundary_triggered_not_per_call():
    state = _run_stint(seed=2, laps=5, noise=NoiseConfig.clean())
    estimator = PaceIntelligenceEstimator()

    first = estimator.update(state)
    second = estimator.update(state)  # same state, no new completed laps

    assert first is second  # cached, not recomputed
