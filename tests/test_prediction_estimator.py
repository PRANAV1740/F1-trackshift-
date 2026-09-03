"""Tests for backend/prediction/estimator.py -- wiring into RaceState."""

from __future__ import annotations

from backend.normalization.stages import default_pipeline
from backend.pace.estimator import PaceIntelligenceEstimator
from backend.prediction.estimator import PositionPredictionEstimator
from backend.prediction.model import TimeDistribution
from backend.state.estimator import RaceStateEstimator
from backend.state.race_state import RaceState
from backend.strategy.engine import StrategyConfig
from backend.strategy.estimator import StrategyEngineEstimator
from backend.tyre.estimator import TyreDegradationEstimator
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig


def test_no_strategy_decision_yet_is_insufficient_data():
    state = RaceState(car_id="44", current_lap=1)
    estimator = PositionPredictionEstimator()

    prediction = estimator.update(state)

    assert prediction.source == "insufficient_opponent_data"
    assert state.predicted_finishing_position is prediction


def test_opponent_source_is_consulted_when_strategy_decision_exists():
    def fake_opponents(state: RaceState) -> list[TimeDistribution]:
        return [TimeDistribution("1", mean_s=4000.0, std_s=5.0)]

    estimator = PositionPredictionEstimator(opponent_source=fake_opponents)
    state = RaceState(car_id="44", current_lap=10, position=3)

    from backend.strategy.engine import StrategyDecision, StrategyDecisionType

    state.current_strategy = StrategyDecision(
        car_id="44", lap=10, decision=StrategyDecisionType.STAY_OUT, compound=None, window=None,
        confidence=0.7, expected_position=3, position_gain=0,
        chosen_projected_time_s=4100.0, chosen_residual_std_s=0.2, chosen_remaining_laps=40,
    )

    prediction = estimator.update(state)

    assert prediction.source == "monte_carlo"
    assert prediction.n_simulations > 0


def test_cached_until_lap_count_changes():
    state = RaceState(car_id="44", current_lap=1)
    estimator = PositionPredictionEstimator()

    first = estimator.update(state)
    second = estimator.update(state)
    assert first is second


def test_end_to_end_without_opponents_is_honestly_insufficient():
    """Live wiring today (single-car simulator, no Phase 14 opponent
    source configured) must never fabricate a position distribution."""

    config = GeneratorConfig(laps=8, noise=NoiseConfig.moderate())
    frames = list(TelemetryGenerator(config, seed=3).frames())

    pipeline = default_pipeline()
    race_state_estimator = RaceStateEstimator()
    tyre_estimator = TyreDegradationEstimator()
    pace_estimator = PaceIntelligenceEstimator()
    strategy_estimator = StrategyEngineEstimator(StrategyConfig(race_total_laps=8))
    prediction_estimator = PositionPredictionEstimator()  # no opponent_source configured

    final_state = None
    for frame in frames:
        result = pipeline.process(frame)
        state = race_state_estimator.update(result)
        if state is not None:
            tyre_estimator.update(state)
            pace_estimator.update(state, tyre_estimator=tyre_estimator)
            strategy_estimator.update(state, tyre_estimator, pace_estimator)
            prediction_estimator.update(state)
            final_state = state

    assert final_state is not None
    assert final_state.predicted_finishing_position.source == "insufficient_opponent_data"
