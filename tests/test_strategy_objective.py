"""Tests for backend/strategy/objective.py -- the explicit objective function."""

from __future__ import annotations

import pytest

from backend.strategy import objective
from backend.telemetry.schema import TyreCompound
from backend.tyre.model import DegradationEstimate


def _estimate(compound=TyreCompound.MEDIUM, rate=0.03, cliff=20, cliff_coeff=0.01, residual=0.1, n=10):
    return DegradationEstimate(
        compound=compound, n_observations=n, base_pace_s=90.0,
        degradation_rate_s_per_lap=rate, cliff_lap=cliff, cliff_coefficient_s_per_lap2=cliff_coeff, residual_std_s=residual,
    )


def test_fallback_estimate_scales_from_reference():
    reference = _estimate(compound=TyreCompound.MEDIUM, rate=0.03)
    fallback = objective.fallback_degradation_estimate(TyreCompound.HARD, reference)

    hard_mult = objective.ASSUMED_COMPOUND_RATE_MULTIPLIER[TyreCompound.HARD]
    medium_mult = objective.ASSUMED_COMPOUND_RATE_MULTIPLIER[TyreCompound.MEDIUM]
    assert fallback.degradation_rate_s_per_lap == pytest.approx(0.03 * hard_mult / medium_mult)
    assert fallback.compound == TyreCompound.HARD
    assert fallback.n_observations == 0


def test_fallback_estimate_without_reference_uses_generic_default():
    fallback = objective.fallback_degradation_estimate(TyreCompound.SOFT, None)
    assert fallback.n_observations == 0
    assert fallback.degradation_rate_s_per_lap > 0


def test_score_stay_out_with_no_estimate_is_a_neutral_zero_score():
    score = objective.score_stay_out(None, None, current_lap=5, current_age_laps=3, current_fuel_kg=80, fuel_burn_rate_kg_per_lap=1.8, remaining_laps=10)
    assert score.total_score_s == 0.0
    assert score.used_fallback_curve is True


def test_score_stay_out_matches_manual_sum():
    from backend.pace.model import project_pace_curve

    est = _estimate()
    score = objective.score_stay_out(est, 90.0, current_lap=5, current_age_laps=3, current_fuel_kg=80.0, fuel_burn_rate_kg_per_lap=1.8, remaining_laps=6)

    curve = project_pace_curve(90.0, est, 5, 3, 80.0, 1.8, 6)
    assert score.projected_stint_time_s == pytest.approx(sum(curve))
    assert score.risk_penalty_s > 0
    assert score.total_score_s == pytest.approx(score.projected_stint_time_s + score.risk_penalty_s + score.failure_penalty_s)


def test_score_pit_includes_pit_loss():
    est = _estimate()
    score = objective.score_pit(
        TyreCompound.MEDIUM, est, est, base_pace_s=90.0, current_lap=5,
        current_fuel_kg=80.0, fuel_burn_rate_kg_per_lap=1.8, remaining_laps=6, pit_loss_s=22.0,
    )
    assert score.pits is True
    assert score.used_fallback_curve is False
    # pit_loss must be part of the total, i.e. removing it should always leave a smaller number
    assert score.projected_stint_time_s > 22.0


def test_score_pit_flags_fallback_when_no_fitted_estimate():
    score = objective.score_pit(
        TyreCompound.HARD, None, _estimate(compound=TyreCompound.MEDIUM), base_pace_s=90.0, current_lap=5,
        current_fuel_kg=80.0, fuel_burn_rate_kg_per_lap=1.8, remaining_laps=6, pit_loss_s=22.0,
    )
    assert score.used_fallback_curve is True
    assert score.failure_penalty_s == objective.NO_FITTED_CURVE_PENALTY_S


def test_score_pit_with_zero_remaining_laps_is_just_pit_loss():
    est = _estimate()
    score = objective.score_pit(
        TyreCompound.MEDIUM, est, est, base_pace_s=90.0, current_lap=49,
        current_fuel_kg=10.0, fuel_burn_rate_kg_per_lap=1.8, remaining_laps=0, pit_loss_s=22.0,
    )
    assert score.projected_stint_time_s == 22.0
