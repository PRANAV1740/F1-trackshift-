"""Tests for backend/opponents/estimator.py and prediction.py -- including
the first genuine multi-car end-to-end simulation in this project.
"""

from __future__ import annotations

import pytest

from backend.normalization.stages import default_pipeline
from backend.opponents.estimator import OpponentIntelligenceEstimator
from backend.opponents.model import ThreatLevel
from backend.opponents.prediction import opponent_distributions_for
from backend.pace.estimator import PaceIntelligenceEstimator
from backend.prediction.estimator import PositionPredictionEstimator
from backend.state.estimator import RaceStateEstimator
from backend.strategy.engine import StrategyConfig
from backend.strategy.estimator import StrategyEngineEstimator
from backend.tyre.estimator import TyreDegradationEstimator
from backend.adapters.simulator_adapter import SimulatorAdapter
from backend.ingestion.service import IngestionService
from simulator.generator.core import GeneratorConfig
from simulator.generator.noise import NoiseConfig
from backend.telemetry.schema import TyreCompound


def test_single_car_update_all_is_a_no_op():
    race_state_estimator = RaceStateEstimator()
    from backend.normalization.base import NormalizationResult
    from backend.telemetry.schema import DataSource, RaceTelemetry
    from datetime import datetime, timezone

    frame = RaceTelemetry(source=DataSource.SIMULATOR, source_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), car_id="44", lap=1)
    race_state_estimator.update(NormalizationResult(raw_frame=frame, normalized_frame=frame, issues=[], changes=[]))

    estimator = OpponentIntelligenceEstimator()
    estimator.update_all(race_state_estimator)  # must not crash with only one car

    state = race_state_estimator.get_state("44")
    assert state.opponent_threats == {}


@pytest.mark.asyncio
async def test_three_car_end_to_end_simulation_produces_real_opponent_intelligence():
    total_laps = 10
    # starting_fuel_kg is deliberately staggered to give the three cars a
    # clear, robust pace differential via the ground-truth fuel-effect
    # model (heavier fuel load = slower, ~0.033s/kg). Two other knobs were
    # tried and rejected while debugging this test (see docs/VALIDATION.md
    # for the full account): (1) compound alone (SOFT/MEDIUM/HARD) only
    # differs in *degradation rate* here, not base pace, so it's too small
    # a signal at low tyre age; (2) v_max_kph barely matters on this
    # synthetic track -- most straights aren't long enough for a car to
    # approach v_max before the next braking zone, so a 40 kph v_max spread
    # produced under 1 second of lap-time difference. Fuel load directly
    # and robustly separates the field.
    configs = [
        GeneratorConfig(car_id="44", laps=total_laps, compound=TyreCompound.MEDIUM, starting_position=1, starting_fuel_kg=40.0, noise=NoiseConfig.moderate()),
        GeneratorConfig(car_id="1", laps=total_laps, compound=TyreCompound.SOFT, starting_position=2, starting_fuel_kg=90.0, noise=NoiseConfig.moderate()),
        GeneratorConfig(car_id="16", laps=total_laps, compound=TyreCompound.HARD, starting_position=3, starting_fuel_kg=140.0, noise=NoiseConfig.moderate()),
    ]
    adapters = [SimulatorAdapter(cfg, seed=100 + i) for i, cfg in enumerate(configs)]

    pipeline = default_pipeline()
    race_state_estimator = RaceStateEstimator()
    tyre_estimator = TyreDegradationEstimator()
    pace_estimator = PaceIntelligenceEstimator()
    strategy_estimator = StrategyEngineEstimator(StrategyConfig(race_total_laps=total_laps))
    opponent_estimator = OpponentIntelligenceEstimator()
    prediction_estimator = PositionPredictionEstimator(
        opponent_source=lambda state: opponent_distributions_for(
            state.car_id, race_state_estimator.all_states(), tyre_estimator,
            remaining_laps=max(total_laps - state.current_lap, 1),
        )
    )

    # Mid-race snapshot of every car's gaps, captured the first time all
    # three cars are confirmed on lap `mid_race_lap`. The FINAL frame of the
    # race is deliberately NOT used for the gap-positivity check below: a
    # car's last recorded frame is always at (or capped near) the very end
    # of its last lap, where progress-fraction naturally approaches the
    # 0.999 cap for every car finishing normally -- at that instant gaps
    # are artificially compressed toward zero regardless of true pace
    # differences, which is a real property of the progress-fraction
    # model's edge behavior, not a bug in the gap computation itself. A
    # mid-race snapshot avoids that edge case.
    # Same reasoning applies to position prediction: by each car's FINAL
    # frame, remaining_laps hits exactly 0 for every car simultaneously
    # (all configured for the same total_laps), which correctly triggers
    # backend/strategy's "race distance exhausted" fallback -- resetting
    # chosen_projected_time_s to None, and therefore
    # PositionPredictionEstimator back to "insufficient_opponent_data" on
    # that final update. That's correct behavior (nothing meaningful to
    # project with zero laps left), not a bug -- but it means the final
    # state is the wrong place to check that opponent data unlocked a real
    # prediction. Captured in the same mid-race snapshot instead.
    mid_race_lap = total_laps // 2
    mid_race_snapshot: dict[str, float] = {}
    mid_race_predictions: dict[str, str] = {}

    def sink(result):
        state = race_state_estimator.update(result)
        if state is None:
            return
        tyre_estimator.update(state)
        pace_estimator.update(state, tyre_estimator=tyre_estimator)
        strategy_estimator.update(state, tyre_estimator, pace_estimator)
        opponent_estimator.update_all(race_state_estimator)
        prediction_estimator.update(state)

        if not mid_race_snapshot and all(
            s.current_lap >= mid_race_lap for s in race_state_estimator.all_states().values()
        ) and len(race_state_estimator.all_states()) == 3:
            for car_id, s in race_state_estimator.all_states().items():
                mid_race_snapshot[car_id] = s.gap_ahead_s
                if s.predicted_finishing_position is not None:
                    mid_race_predictions[car_id] = s.predicted_finishing_position.source

    service = IngestionService(adapters=adapters, pipeline=pipeline, sinks=[sink])
    await service.run()

    all_states = race_state_estimator.all_states()
    assert len(all_states) == 3

    # Positions must be a permutation of 1, 2, 3 -- computed by the order tracker, not left as the static config value.
    positions = sorted(s.position for s in all_states.values())
    assert positions == [1, 2, 3]

    # Every car must have opponent summaries for the other two.
    for state in all_states.values():
        assert set(state.opponent_threats.keys()) == {s.car_id for s in all_states.values()} - {state.car_id}
        for summary in state.opponent_threats.values():
            assert summary.undercut_threat in (ThreatLevel.HIGH, ThreatLevel.MEDIUM, ThreatLevel.LOW, ThreatLevel.NONE)

    # Mid-race: the leader's gap_ahead_s must be None, and every follower's
    # gap_ahead_s must be a positive number (they trail someone).
    assert mid_race_snapshot, "mid-race snapshot was never captured"
    non_leader_gaps = [g for g in mid_race_snapshot.values() if g is not None]
    assert len(non_leader_gaps) >= 2  # at least two of the three cars trail someone
    assert all(g > 0 for g in non_leader_gaps)

    # Mid-race, position prediction must now have real opponent data --
    # source "monte_carlo", not "insufficient_opponent_data" -- for at
    # least one car, proving Phase 14's opponent data actually unlocked
    # Phase 11's prediction rather than it staying permanently gated.
    assert mid_race_predictions, "mid-race predictions were never captured"
    assert "monte_carlo" in mid_race_predictions.values()

    for state in all_states.values():
        prediction = state.predicted_finishing_position
        if prediction is not None and prediction.source == "monte_carlo":
            assert sum(prediction.position_probabilities.values()) == pytest.approx(1.0, abs=1e-6)
