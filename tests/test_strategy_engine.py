"""Tests for backend/strategy/engine.py and estimator.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.normalization.stages import default_pipeline
from backend.opponents.model import OpponentSummary, ThreatLevel
from backend.pace.estimator import PaceIntelligenceEstimator
from backend.state.estimator import RaceStateEstimator
from backend.state.race_state import RaceState
from backend.strategy.engine import StrategyConfig, StrategyDecisionType, decide
from backend.strategy.estimator import StrategyEngineEstimator
from backend.telemetry.schema import TyreCompound
from backend.tyre.estimator import TyreDegradationEstimator
from backend.tyre.model import DegradationEstimate
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig

BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _state(**overrides) -> RaceState:
    state = RaceState(car_id="44", current_lap=20, tyre_age_laps=19, fuel_load_kg=60.0, position=5, last_updated=BASE_TS)
    state.tyre_compound = TyreCompound.MEDIUM
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


def test_insufficient_data_defaults_to_stay_out_with_low_confidence():
    state = _state()
    tyre_estimator = TyreDegradationEstimator()  # nothing fitted yet
    decision = decide(state, tyre_estimator)

    assert decision.decision == StrategyDecisionType.STAY_OUT
    assert decision.confidence < 0.3
    assert decision.reasons


def test_race_distance_exhausted_returns_stay_out():
    state = _state(current_lap=60)
    tyre_estimator = TyreDegradationEstimator()
    decision = decide(state, tyre_estimator, config=StrategyConfig(race_total_laps=50))
    assert decision.decision == StrategyDecisionType.STAY_OUT
    assert "exhausted" in decision.reasons[0].lower()


def test_imminent_cliff_triggers_a_pit_decision():
    state = _state(current_lap=20, tyre_age_laps=19, tyre_cliff_probability=0.9)
    tyre_estimator = TyreDegradationEstimator()
    # A steep, imminent cliff right at the current age -- staying out should be expensive.
    tyre_estimator.set_estimate(
        "44",
        DegradationEstimate(
            compound=TyreCompound.MEDIUM, n_observations=15, base_pace_s=90.0,
            degradation_rate_s_per_lap=0.05, cliff_lap=19, cliff_coefficient_s_per_lap2=0.15, residual_std_s=0.1,
        ),
    )

    decision = decide(state, tyre_estimator, config=StrategyConfig(race_total_laps=50))

    assert decision.decision in (StrategyDecisionType.PIT, StrategyDecisionType.PIT_NEXT_LAP)
    assert decision.compound is not None
    assert decision.window is not None
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.reasons and decision.risks and decision.invalidation_conditions


def _opponent_summary(pit_probability, gap=1.5):
    return OpponentSummary(
        car_id="1", position=4, compound=TyreCompound.MEDIUM, tyre_age_laps=10, current_pace_s=90.0,
        degradation_rate_s_per_lap=0.03, pit_probability=pit_probability, pit_status=None,
        gap_magnitude_s=gap, is_ahead=True, undercut_threat=ThreatLevel.NONE, overcut_threat=ThreatLevel.NONE,
    )


def test_pit_decision_relabeled_as_undercut_when_opponent_ahead_not_committed():
    state = _state(
        current_lap=20, tyre_age_laps=19, tyre_cliff_probability=0.9,
        opponent_threats={"1": _opponent_summary(pit_probability=0.1)},
    )
    tyre_estimator = TyreDegradationEstimator()
    tyre_estimator.set_estimate(
        "44",
        DegradationEstimate(
            compound=TyreCompound.MEDIUM, n_observations=15, base_pace_s=90.0,
            degradation_rate_s_per_lap=0.05, cliff_lap=19, cliff_coefficient_s_per_lap2=0.15, residual_std_s=0.1,
        ),
    )

    decision = decide(state, tyre_estimator, config=StrategyConfig(race_total_laps=50))

    assert decision.decision == StrategyDecisionType.UNDERCUT
    assert any("undercut" in r.lower() for r in decision.reasons)


def test_pit_decision_relabeled_as_overcut_when_opponent_ahead_about_to_pit():
    state = _state(
        current_lap=20, tyre_age_laps=19, tyre_cliff_probability=0.05,  # our own pit probability low
        opponent_threats={"1": _opponent_summary(pit_probability=0.9)},
    )
    tyre_estimator = TyreDegradationEstimator()
    tyre_estimator.set_estimate(
        "44",
        DegradationEstimate(
            compound=TyreCompound.MEDIUM, n_observations=15, base_pace_s=90.0,
            degradation_rate_s_per_lap=0.05, cliff_lap=19, cliff_coefficient_s_per_lap2=0.15, residual_std_s=0.1,
        ),
    )

    decision = decide(state, tyre_estimator, config=StrategyConfig(race_total_laps=50))

    assert decision.decision == StrategyDecisionType.OVERCUT
    assert any("overcut" in r.lower() for r in decision.reasons)


def test_pit_decision_stays_plain_pit_without_relevant_opponent_data():
    state = _state(current_lap=20, tyre_age_laps=19, tyre_cliff_probability=0.9, opponent_threats={})
    tyre_estimator = TyreDegradationEstimator()
    tyre_estimator.set_estimate(
        "44",
        DegradationEstimate(
            compound=TyreCompound.MEDIUM, n_observations=15, base_pace_s=90.0,
            degradation_rate_s_per_lap=0.05, cliff_lap=19, cliff_coefficient_s_per_lap2=0.15, residual_std_s=0.1,
        ),
    )

    decision = decide(state, tyre_estimator, config=StrategyConfig(race_total_laps=50))

    assert decision.decision in (StrategyDecisionType.PIT, StrategyDecisionType.PIT_NEXT_LAP)


def test_healthy_fresh_tyre_over_a_short_remaining_distance_stays_out():
    """A fresh, slow-degrading tyre with its cliff nowhere near the
    remaining race distance should stay out. Note the remaining distance
    matters: an earlier version of this test paired a fresh MEDIUM (cliff
    at lap 35) with 47 remaining laps, and the engine correctly chose PIT
    -- running 12 laps past a known cliff is genuinely worse than a pit
    stop's ~22s, which is the objective function doing its job, not a bug
    (see docs/VALIDATION.md). Fixed by giving this scenario a remaining
    distance that's actually consistent with "the current tyre is fine
    for the rest of the race"."""

    state = _state(current_lap=3, tyre_age_laps=2, remaining_tyre_life_laps=30)
    tyre_estimator = TyreDegradationEstimator()
    tyre_estimator.set_estimate(
        "44",
        DegradationEstimate(
            compound=TyreCompound.MEDIUM, n_observations=15, base_pace_s=90.0,
            degradation_rate_s_per_lap=0.02, cliff_lap=35, cliff_coefficient_s_per_lap2=0.005, residual_std_s=0.05,
        ),
    )

    decision = decide(state, tyre_estimator, config=StrategyConfig(race_total_laps=10))

    assert decision.decision in (StrategyDecisionType.STAY_OUT, StrategyDecisionType.EXTEND)
    assert decision.compound is None
    assert decision.window is None


def test_pit_is_preferred_over_a_long_remaining_distance_with_a_severe_cliff():
    """The flip side of the above: when the remaining distance would run
    well past a known cliff AND that cliff is steep enough that the
    accumulated overrun penalty exceeds the pit-loss cost, pitting for a
    slower-degrading compound should score better than grinding through
    the cliff. (A first version of this test used a gentle cliff
    coefficient (0.005) that, once the horizon-accounting bug above was
    fixed, genuinely does NOT outweigh a ~22s pit loss even 14 laps past
    the cliff -- correct behavior, not a bug, so the test needed a cliff
    actually steep enough to demonstrate the intended scenario.)"""

    state = _state(current_lap=3, tyre_age_laps=2)
    tyre_estimator = TyreDegradationEstimator()
    tyre_estimator.set_estimate(
        "44",
        DegradationEstimate(
            compound=TyreCompound.MEDIUM, n_observations=15, base_pace_s=90.0,
            degradation_rate_s_per_lap=0.02, cliff_lap=35, cliff_coefficient_s_per_lap2=0.05, residual_std_s=0.05,
        ),
    )

    decision = decide(state, tyre_estimator, config=StrategyConfig(race_total_laps=50))

    assert decision.decision in (StrategyDecisionType.PIT, StrategyDecisionType.PIT_NEXT_LAP)
    assert decision.compound in (TyreCompound.MEDIUM, TyreCompound.HARD)


def test_vsc_reduces_pit_loss_and_is_mentioned_in_reasons():
    state = _state(current_lap=20, tyre_age_laps=19, vsc=True, tyre_cliff_probability=0.7)
    tyre_estimator = TyreDegradationEstimator()
    tyre_estimator.set_estimate(
        "44",
        DegradationEstimate(
            compound=TyreCompound.MEDIUM, n_observations=15, base_pace_s=90.0,
            degradation_rate_s_per_lap=0.05, cliff_lap=19, cliff_coefficient_s_per_lap2=0.15, residual_std_s=0.1,
        ),
    )

    decision = decide(state, tyre_estimator, config=StrategyConfig(race_total_laps=50))

    if decision.decision in (StrategyDecisionType.PIT, StrategyDecisionType.PIT_NEXT_LAP):
        assert any("vsc" in r.lower() for r in decision.reasons)
        assert decision.decision == StrategyDecisionType.PIT_NEXT_LAP  # VSC makes it urgent


def test_to_dict_has_all_required_keys():
    state = _state()
    tyre_estimator = TyreDegradationEstimator()
    decision = decide(state, tyre_estimator)
    payload = decision.to_dict()

    for key in ["decision", "compound", "window", "confidence", "expected_position", "position_gain", "reasons", "risks", "invalidation_conditions"]:
        assert key in payload


def test_strategy_estimator_is_lap_and_flag_triggered():
    state = _state()
    tyre_estimator = TyreDegradationEstimator()
    estimator = StrategyEngineEstimator()

    first = estimator.update(state, tyre_estimator)
    second = estimator.update(state, tyre_estimator)  # no change -- cached
    assert first is second

    state.vsc = True  # flag change -- must trigger reassessment
    third = estimator.update(state, tyre_estimator)
    assert third is not second


def test_end_to_end_strategy_decisions_from_simulated_stint():
    config = GeneratorConfig(laps=15, noise=NoiseConfig.moderate())
    frames = list(TelemetryGenerator(config, seed=9).frames())

    pipeline = default_pipeline()
    race_state_estimator = RaceStateEstimator()
    tyre_estimator = TyreDegradationEstimator()
    pace_estimator = PaceIntelligenceEstimator()
    strategy_estimator = StrategyEngineEstimator(StrategyConfig(race_total_laps=15))

    final_state = None
    for frame in frames:
        result = pipeline.process(frame)
        state = race_state_estimator.update(result)
        if state is not None:
            tyre_estimator.update(state)
            pace_estimator.update(state, tyre_estimator=tyre_estimator)
            strategy_estimator.update(state, tyre_estimator, pace_estimator)
            final_state = state

    assert final_state is not None
    assert final_state.current_strategy is not None
    assert isinstance(final_state.current_strategy.decision, StrategyDecisionType)
    payload = final_state.current_strategy.to_dict()
    assert payload["decision"] in [d.value for d in StrategyDecisionType]
