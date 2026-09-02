"""Tests for backend/pace/model.py."""

from __future__ import annotations

import pytest

from backend.pace.model import estimate_pace
from backend.state.race_state import LapRecord
from backend.telemetry.schema import TrackState, TyreCompound
from backend.tyre.model import DegradationEstimate


def _lap(lap, lap_time_s, was_pit_lap=False, track_state=TrackState.GREEN, confidence=1.0, tyre_age=None):
    return LapRecord(
        lap=lap,
        lap_time_s=lap_time_s,
        tyre_compound=TyreCompound.MEDIUM,
        tyre_age_laps=tyre_age if tyre_age is not None else lap - 1,
        fuel_load_kg_start=100.0 - lap,
        was_pit_lap=was_pit_lap,
        track_state_at_end=track_state,
        avg_confidence=confidence,
    )


def test_no_completed_laps_gives_insufficient_data():
    estimate = estimate_pace([], current_lap=1, current_tyre_age_laps=0, current_fuel_load_kg=100.0, degradation_estimate=None)
    assert estimate.source == "insufficient_data"
    assert estimate.current_pace_s is None
    assert estimate.expected_clean_pace_s is None


def test_current_pace_reflects_most_recent_lap_even_if_unclean():
    laps = [_lap(1, 90.0), _lap(2, 120.0, was_pit_lap=True)]
    estimate = estimate_pace(laps, current_lap=3, current_tyre_age_laps=1, current_fuel_load_kg=95.0, degradation_estimate=None)
    assert estimate.current_pace_s == 120.0


def test_rolling_average_fallback_excludes_unclean_laps():
    laps = [_lap(1, 90.0), _lap(2, 200.0, was_pit_lap=True), _lap(3, 91.0), _lap(4, 92.0)]
    estimate = estimate_pace(laps, current_lap=5, current_tyre_age_laps=3, current_fuel_load_kg=90.0, degradation_estimate=None)

    assert estimate.source == "rolling_average"
    assert estimate.expected_clean_pace_s == pytest.approx((90.0 + 91.0 + 92.0) / 3)


def test_tyre_model_source_used_when_degradation_estimate_available():
    degradation = DegradationEstimate(
        compound=TyreCompound.MEDIUM,
        n_observations=10,
        base_pace_s=90.0,
        degradation_rate_s_per_lap=0.03,
        cliff_lap=20,
        cliff_coefficient_s_per_lap2=0.01,
        residual_std_s=0.1,
    )
    laps = [_lap(1, 90.0), _lap(2, 90.5), _lap(3, 91.0)]

    estimate = estimate_pace(laps, current_lap=4, current_tyre_age_laps=3, current_fuel_load_kg=95.0, degradation_estimate=degradation)

    assert estimate.source == "tyre_model"
    expected = 90.0 + estimate.contributions["fuel_effect_s"] + estimate.contributions["track_evolution_s"] + degradation.degradation_at(3)
    assert estimate.expected_clean_pace_s == pytest.approx(expected)
    assert set(estimate.contributions) == {"base_pace_s", "fuel_effect_s", "track_evolution_s", "degradation_s"}


def test_pace_delta_is_current_minus_expected():
    laps = [_lap(1, 90.0), _lap(2, 91.0), _lap(3, 95.0)]
    estimate = estimate_pace(laps, current_lap=4, current_tyre_age_laps=3, current_fuel_load_kg=90.0, degradation_estimate=None)
    assert estimate.pace_delta_s == pytest.approx(estimate.current_pace_s - estimate.expected_clean_pace_s)


def test_pace_trend_is_positive_for_worsening_laps():
    laps = [_lap(i, 90.0 + i * 0.5) for i in range(1, 6)]
    estimate = estimate_pace(laps, current_lap=6, current_tyre_age_laps=5, current_fuel_load_kg=90.0, degradation_estimate=None)
    assert estimate.pace_trend_s_per_lap == pytest.approx(0.5, abs=0.01)


def test_pace_trend_is_none_with_too_few_clean_laps():
    laps = [_lap(1, 90.0), _lap(2, 91.0)]
    estimate = estimate_pace(laps, current_lap=3, current_tyre_age_laps=2, current_fuel_load_kg=90.0, degradation_estimate=None)
    assert estimate.pace_trend_s_per_lap is None
