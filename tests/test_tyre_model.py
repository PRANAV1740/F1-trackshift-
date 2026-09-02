"""Tests for backend/tyre/model.py -- the core TrackShift 2026 problem.

Two-tier validation, deliberately kept separate:

1. A controlled synthetic test with NO model misspecification (lap times
   built from the exact same assumed fuel/evolution functions the
   estimator itself uses) -- isolates whether the regression machinery
   (weighted least squares + cliff grid search + posterior) is correct,
   independent of any physics-assumption mismatch.
2. A simulator-based test using the real generator's ground truth (which
   uses DIFFERENT fuel/evolution constants than this module assumes, on
   purpose -- see backend/tyre/model.py's module docstring) -- validates
   the realistic, imperfect-physics scenario with a shape/trend-based
   tolerance (correlation) rather than expecting exact numeric recovery,
   because exact recovery isn't actually the honest claim to make here.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from backend.tyre.model import (
    DegradationEstimate,
    MIN_OBSERVATIONS,
    TyreObservation,
    assumed_fuel_effect_s,
    assumed_track_evolution_gain_s,
    fit_degradation_model,
)
from backend.telemetry.schema import TyreCompound
from simulator.generator.ground_truth import COMPOUND_MODELS
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig
from backend.normalization.stages import default_pipeline
from backend.state.estimator import RaceStateEstimator


# --- Regression machinery: controlled recovery (no model misspecification) --


def test_fit_recovers_known_degradation_with_no_model_misspecification():
    rng = random.Random(0)
    true_rate = 0.04
    true_cliff = 18
    true_cliff_coeff = 0.02
    base_pace = 90.0

    observations = []
    for age in range(0, 30):
        lap = age + 1
        fuel = 100.0 - 2.0 * age
        true_degradation = true_rate * age + true_cliff_coeff * max(0, age - true_cliff) ** 2
        noise = rng.gauss(0, 0.05)
        lap_time = base_pace + assumed_fuel_effect_s(fuel) + assumed_track_evolution_gain_s(lap) + true_degradation + noise
        observations.append(
            TyreObservation(lap=lap, tyre_age_laps=age, compound=TyreCompound.MEDIUM, fuel_load_kg=fuel, lap_time_s=lap_time)
        )

    estimate = fit_degradation_model(observations)

    assert estimate is not None
    assert estimate.degradation_rate_s_per_lap == pytest.approx(true_rate, abs=0.015)
    assert abs(estimate.cliff_lap - true_cliff) <= 5
    assert estimate.base_pace_s == pytest.approx(base_pace, abs=1.0)
    assert estimate.residual_std_s < 0.3  # noise was std=0.05; fit should track it


def test_fit_returns_none_with_insufficient_observations():
    observations = [
        TyreObservation(lap=i + 1, tyre_age_laps=i, compound=TyreCompound.SOFT, fuel_load_kg=100.0, lap_time_s=90.0 + i * 0.1)
        for i in range(MIN_OBSERVATIONS - 1)
    ]
    assert fit_degradation_model(observations) is None


def test_cliff_posterior_sums_to_one():
    rng = random.Random(1)
    observations = [
        TyreObservation(
            lap=age + 1,
            tyre_age_laps=age,
            compound=TyreCompound.HARD,
            fuel_load_kg=90.0,
            lap_time_s=88.0 + 0.02 * age + rng.gauss(0, 0.02),
        )
        for age in range(20)
    ]
    estimate = fit_degradation_model(observations)
    assert estimate is not None
    assert sum(estimate.cliff_posterior.values()) == pytest.approx(1.0, abs=1e-6)


# --- DegradationEstimate derived-quantity methods ----------------------------


def _manual_estimate() -> DegradationEstimate:
    return DegradationEstimate(
        compound=TyreCompound.MEDIUM,
        n_observations=20,
        base_pace_s=90.0,
        degradation_rate_s_per_lap=0.03,
        cliff_lap=15,
        cliff_coefficient_s_per_lap2=0.01,
        residual_std_s=0.1,
        cliff_posterior={13: 0.1, 15: 0.6, 17: 0.3},
    )


def test_degradation_at_is_zero_before_any_age_and_grows_after():
    est = _manual_estimate()
    assert est.degradation_at(0) == 0.0
    assert est.degradation_at(5) == pytest.approx(0.15)
    assert est.degradation_at(20) > est.degradation_at(15) > est.degradation_at(5)


def test_degradation_rate_increases_past_the_cliff():
    est = _manual_estimate()
    rate_before = est.degradation_rate_at(10)
    rate_after = est.degradation_rate_at(20)
    assert rate_after > rate_before
    assert rate_before == pytest.approx(0.03)


def test_degradation_acceleration_is_zero_before_cliff_nonzero_after():
    est = _manual_estimate()
    assert est.degradation_acceleration_at(10) == 0.0
    assert est.degradation_acceleration_at(20) == pytest.approx(0.02)


def test_cliff_probability_within_uses_posterior_mass():
    est = _manual_estimate()
    # cliffs <= 15 + 0 = 15: {13: 0.1, 15: 0.6} = 0.7
    assert est.cliff_probability_within(15, lookahead_laps=0) == pytest.approx(0.7)
    # all three candidates are <= 15 + 3
    assert est.cliff_probability_within(15, lookahead_laps=3) == pytest.approx(1.0)


def test_remaining_competitive_life_finds_threshold_crossing():
    est = _manual_estimate()
    remaining = est.remaining_competitive_life_laps(age_laps=10, max_acceptable_extra_penalty_s=0.5)
    assert remaining is not None
    assert est.degradation_at(10 + remaining) - est.degradation_at(10) > 0.5
    assert est.degradation_at(10 + remaining - 1) - est.degradation_at(10) <= 0.5


def test_remaining_competitive_life_returns_none_if_never_reached():
    est = DegradationEstimate(
        compound=TyreCompound.HARD, n_observations=10, base_pace_s=90.0,
        degradation_rate_s_per_lap=0.001, cliff_lap=None, cliff_coefficient_s_per_lap2=0.0, residual_std_s=0.1,
    )
    assert est.remaining_competitive_life_laps(age_laps=0, max_acceptable_extra_penalty_s=5.0, horizon_laps=10) is None


# --- Realistic validation against simulator ground truth (shape-based) -----


def _lap_records_for_stint(seed: int, compound: TyreCompound, laps: int, starting_lap: int, noise: NoiseConfig):
    """Runs one full simulated stint through the real pipeline (ingestion
    normalization + state estimation), returning usable TyreObservations.

    `starting_lap` simulates "this stint starts later in a longer race,
    after a pit stop reset tyre age to 0" via GeneratorConfig.starting_lap
    -- which makes the GENERATED data itself (not just the fitting step)
    reflect a later, more track-evolved race lap while tyre age and fuel
    stay stint-relative. This is what breaks the tyre-age-vs-lap-number
    collinearity that makes single-stint decomposition unidentifiable (see
    backend/tyre/model.py). An earlier version of this test faked the
    offset only when building TyreObservations, without the underlying
    telemetry reflecting it -- that produced internally-inconsistent data
    (assumed evolution removal didn't match what was actually generated)
    and the estimator recovered a negative correlation against ground
    truth. Fixed by generating honestly instead of faking it after the
    fact -- see docs/VALIDATION.md.
    """

    config = GeneratorConfig(laps=laps, compound=compound, noise=noise, starting_lap=starting_lap)
    frames = list(TelemetryGenerator(config, seed=seed).frames())

    pipeline = default_pipeline()
    estimator = RaceStateEstimator()
    for frame in frames:
        result = pipeline.process(frame)
        estimator.update(result)

    state = estimator.get_state(config.car_id)
    records = []
    for lap_record in state.completed_laps:
        if (
            lap_record.tyre_compound is None
            or lap_record.fuel_load_kg_start is None
            or lap_record.lap_time_s is None
            or lap_record.was_pit_lap
        ):
            continue
        records.append(
            TyreObservation(
                lap=lap_record.lap,
                tyre_age_laps=lap_record.tyre_age_laps,
                compound=lap_record.tyre_compound,
                fuel_load_kg=lap_record.fuel_load_kg_start,
                lap_time_s=lap_record.lap_time_s,
                confidence=lap_record.avg_confidence,
            )
        )
    return records


def test_estimator_recovers_degradation_trend_from_realistic_multi_stint_data():
    compound = TyreCompound.MEDIUM
    noise = NoiseConfig.moderate()

    stint_a = _lap_records_for_stint(seed=10, compound=compound, laps=20, starting_lap=1, noise=noise)
    stint_b = _lap_records_for_stint(seed=11, compound=compound, laps=20, starting_lap=26, noise=noise)
    observations = stint_a + stint_b
    assert len(observations) >= 2 * MIN_OBSERVATIONS

    estimate = fit_degradation_model(observations)
    assert estimate is not None

    truth = COMPOUND_MODELS[compound]
    ages = list(range(0, 20))
    fitted_curve = np.array([estimate.degradation_at(a) for a in ages])
    true_curve = np.array([truth.pace_penalty_s(a) for a in ages])

    correlation = np.corrcoef(fitted_curve, true_curve)[0, 1]
    assert correlation > 0.85, f"fitted degradation shape should track ground truth (corr={correlation:.2f})"

    # The fitted degradation rate should at least have the right sign and
    # rough order of magnitude -- not exact, since fuel/evolution are
    # assumed rather than fit (see model docstring).
    assert 0.0 < estimate.degradation_rate_s_per_lap < 3 * truth.linear_rate_s_per_lap
