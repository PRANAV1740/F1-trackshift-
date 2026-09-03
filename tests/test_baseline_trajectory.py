"""Tests for backend/state/baseline.py and baseline_estimator.py."""

from __future__ import annotations

import pytest

from backend.pace.estimator import PaceIntelligenceEstimator
from backend.state.baseline import build_baseline_trajectory, estimate_fuel_burn_rate, DEFAULT_ASSUMED_FUEL_BURN_KG_PER_LAP
from backend.state.baseline_estimator import BaselineTrajectoryEstimator
from backend.state.race_state import LapRecord, RaceState
from backend.telemetry.schema import TrackState, TyreCompound
from backend.tyre.estimator import TyreDegradationEstimator
from backend.tyre.model import DegradationEstimate
from backend.normalization.stages import default_pipeline
from backend.state.estimator import RaceStateEstimator
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig


def _state_with_history(current_lap=10, tyre_age=9, fuel=80.0, position=4) -> RaceState:
    state = RaceState(car_id="44", current_lap=current_lap, tyre_age_laps=tyre_age, fuel_load_kg=fuel, position=position)
    state.tyre_compound = TyreCompound.MEDIUM
    state.gap_ahead_s = 3.2
    state.gap_behind_s = 1.1
    state.completed_laps = [
        LapRecord(
            lap=i + 1, lap_time_s=90.0 + i * 0.05, tyre_compound=TyreCompound.MEDIUM, tyre_age_laps=i,
            fuel_load_kg_start=110.0 - i * 3.0, was_pit_lap=False, track_state_at_end=TrackState.GREEN, avg_confidence=1.0,
        )
        for i in range(current_lap - 1)
    ]
    return state


def test_projection_without_degradation_estimate_has_no_pace_but_has_fuel_and_age():
    state = _state_with_history()
    trajectory = build_baseline_trajectory(state, degradation_estimate=None, pace_estimate=None, horizon_laps=5)

    assert len(trajectory.projection) == 5
    first = trajectory.projection[0]
    assert first.lap == state.current_lap + 1
    assert first.projected_tyre_age_laps == state.tyre_age_laps + 1
    assert first.projected_pace_s is None
    assert first.projected_fuel_load_kg < state.fuel_load_kg


def test_projection_with_degradation_estimate_produces_pace_and_correct_arithmetic():
    """Pace itself is NOT guaranteed monotonic over the horizon -- fuel
    burn-off genuinely makes the car faster early in a stint even as the
    tyre degrades (same phenomenon validated in test_simulator_generator.py
    and test_tyre_model.py), so asserting pace always worsens would be
    wrong. What IS guaranteed by construction is that the degradation
    component alone is non-decreasing with age, and that pace is exactly
    base_pace + fuel_effect + evolution + degradation at each point."""

    from backend.tyre.model import assumed_fuel_effect_s, assumed_track_evolution_gain_s

    state = _state_with_history()
    degradation = DegradationEstimate(
        compound=TyreCompound.MEDIUM, n_observations=9, base_pace_s=90.0,
        degradation_rate_s_per_lap=0.05, cliff_lap=25, cliff_coefficient_s_per_lap2=0.01, residual_std_s=0.1,
    )

    trajectory = build_baseline_trajectory(state, degradation_estimate=degradation, pace_estimate=None, horizon_laps=5)

    degradations = [p.projected_degradation_s for p in trajectory.projection]
    assert all(p is not None for p in degradations)
    assert degradations == sorted(degradations)

    for point in trajectory.projection:
        expected_pace = (
            degradation.base_pace_s
            + assumed_fuel_effect_s(point.projected_fuel_load_kg)
            + assumed_track_evolution_gain_s(point.lap)
            + point.projected_degradation_s
        )
        assert point.projected_pace_s == pytest.approx(expected_pace)


def test_recommended_pit_window_present_when_remaining_life_known():
    state = _state_with_history(current_lap=10, tyre_age=9)
    degradation = DegradationEstimate(
        compound=TyreCompound.MEDIUM, n_observations=9, base_pace_s=90.0,
        degradation_rate_s_per_lap=0.05, cliff_lap=12, cliff_coefficient_s_per_lap2=0.05, residual_std_s=0.1,
    )
    trajectory = build_baseline_trajectory(state, degradation_estimate=degradation, pace_estimate=None, horizon_laps=15)

    assert trajectory.recommended_pit_window is not None
    start, end = trajectory.recommended_pit_window
    assert start <= end
    assert start > state.current_lap


def test_recommended_pit_window_is_none_without_degradation_estimate():
    state = _state_with_history()
    trajectory = build_baseline_trajectory(state, degradation_estimate=None, pace_estimate=None)
    assert trajectory.recommended_pit_window is None


def test_naive_position_and_gaps_are_carried_forward_from_current_state():
    state = _state_with_history(position=7)
    trajectory = build_baseline_trajectory(state, degradation_estimate=None, pace_estimate=None)

    assert trajectory.naive_position == 7
    assert trajectory.naive_gap_ahead_s == state.gap_ahead_s
    assert trajectory.naive_gap_behind_s == state.gap_behind_s
    assert "naive" in trajectory.method_note.lower()


def test_fuel_burn_rate_estimated_from_history_when_available():
    state = _state_with_history()
    rate = estimate_fuel_burn_rate(state)
    assert rate > 0
    assert rate != DEFAULT_ASSUMED_FUEL_BURN_KG_PER_LAP  # should be derived, not the fallback


def test_fuel_burn_rate_falls_back_to_default_with_no_history():
    state = RaceState(car_id="1", current_lap=1, fuel_load_kg=110.0)
    rate = estimate_fuel_burn_rate(state)
    assert rate == DEFAULT_ASSUMED_FUEL_BURN_KG_PER_LAP


def test_baseline_estimator_is_lap_boundary_triggered():
    state = _state_with_history()
    estimator = BaselineTrajectoryEstimator()

    first = estimator.update(state)
    second = estimator.update(state)

    assert first is second


def test_end_to_end_baseline_trajectory_from_simulated_stint():
    config = GeneratorConfig(laps=12, noise=NoiseConfig.moderate())
    frames = list(TelemetryGenerator(config, seed=5).frames())

    pipeline = default_pipeline()
    race_state_estimator = RaceStateEstimator()
    tyre_estimator = TyreDegradationEstimator()
    pace_estimator = PaceIntelligenceEstimator()
    baseline_estimator = BaselineTrajectoryEstimator(horizon_laps=8)

    for frame in frames:
        result = pipeline.process(frame)
        state = race_state_estimator.update(result)
        if state is not None:
            tyre_estimator.update(state)
            pace_estimator.update(state, tyre_estimator=tyre_estimator)
            baseline_estimator.update(state, tyre_estimator=tyre_estimator, pace_estimator=pace_estimator)

    assert state.baseline_trajectory is not None
    assert len(state.baseline_trajectory.projection) == 8
    assert state.baseline_trajectory.generated_at_lap == state.current_lap
