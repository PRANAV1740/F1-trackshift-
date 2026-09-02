"""Tests for backend/tyre/estimator.py -- wiring the tyre model into RaceState."""

from __future__ import annotations

from backend.normalization.stages import default_pipeline
from backend.state.estimator import RaceStateEstimator
from backend.tyre.estimator import MIN_CONFIDENCE_TO_USE_LAP, TyreDegradationEstimator
from backend.tyre.model import MIN_OBSERVATIONS
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig


def _run_stint(seed: int, laps: int, noise: NoiseConfig):
    config = GeneratorConfig(laps=laps, noise=noise)
    frames = list(TelemetryGenerator(config, seed=seed).frames())

    pipeline = default_pipeline()
    race_state_estimator = RaceStateEstimator()
    tyre_estimator = TyreDegradationEstimator()

    for frame in frames:
        result = pipeline.process(frame)
        state = race_state_estimator.update(result)
        if state is not None:
            tyre_estimator.update(state)

    return race_state_estimator.get_state(config.car_id), tyre_estimator


def test_state_fields_stay_none_until_enough_laps_observed():
    state, tyre_estimator = _run_stint(seed=1, laps=2, noise=NoiseConfig.clean())

    assert len(state.completed_laps) < MIN_OBSERVATIONS
    assert state.estimated_degradation_s is None
    assert state.degradation_rate_s_per_lap is None
    assert state.tyre_cliff_probability is None


def test_state_fields_populate_once_enough_laps_observed():
    state, tyre_estimator = _run_stint(seed=1, laps=12, noise=NoiseConfig.moderate())

    assert len(state.completed_laps) >= MIN_OBSERVATIONS
    assert state.estimated_degradation_s is not None
    assert state.degradation_rate_s_per_lap is not None
    assert state.degradation_acceleration_s_per_lap2 is not None
    assert 0.0 <= state.tyre_cliff_probability <= 1.0
    assert state.estimated_degradation_s >= 0.0  # tyre age 11 should show some wear


def test_estimate_is_retrievable_directly():
    state, tyre_estimator = _run_stint(seed=2, laps=10, noise=NoiseConfig.clean())

    estimate = tyre_estimator.get_estimate(state.car_id, state.tyre_compound)
    assert estimate is not None
    assert estimate.n_observations >= MIN_OBSERVATIONS


def test_refit_is_not_triggered_mid_lap_only_on_lap_completion():
    """Calling update() with the same RaceState (no new completed laps)
    must not change the underlying observation count -- refit is
    lap-boundary-triggered, not per-call."""

    state, tyre_estimator = _run_stint(seed=3, laps=6, noise=NoiseConfig.clean())
    key = (state.car_id, state.tyre_compound)
    before = len(tyre_estimator._observations[key])

    tyre_estimator.update(state)  # no new completed laps since last call
    after = len(tyre_estimator._observations[key])

    assert before == after


def test_low_confidence_laps_are_excluded_from_fitting():
    """A lap whose avg_confidence is below the usability threshold must not
    be added as an observation."""

    from backend.state.race_state import LapRecord, RaceState
    from backend.telemetry.schema import TyreCompound

    estimator = TyreDegradationEstimator()
    state = RaceState(car_id="99", tyre_compound=TyreCompound.SOFT, tyre_age_laps=5)
    state.completed_laps = [
        LapRecord(
            lap=i + 1,
            lap_time_s=90.0 + i * 0.05,
            tyre_compound=TyreCompound.SOFT,
            tyre_age_laps=i,
            fuel_load_kg_start=100.0 - i,
            was_pit_lap=False,
            track_state_at_end=None,
            avg_confidence=MIN_CONFIDENCE_TO_USE_LAP - 0.1,
        )
        for i in range(MIN_OBSERVATIONS + 2)
    ]

    estimator.update(state)

    key = ("99", TyreCompound.SOFT)
    assert len(estimator._observations[key]) == 0
    assert estimator.get_estimate("99", TyreCompound.SOFT) is None
