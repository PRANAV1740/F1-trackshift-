"""End-to-end proof that a simulator-injected SC/VSC period propagates all
the way through the pipeline to an immediate strategy reassessment --
the actual behavior Phase 12 ("event-aware pit-loss modelling... the
strategy engine must react automatically") asks for, not just unit-level
claims about it.
"""

from __future__ import annotations

from backend.events.detector import EventDetectionEngine
from backend.events.model import EventType
from backend.normalization.stages import default_pipeline
from backend.pace.estimator import PaceIntelligenceEstimator
from backend.state.estimator import RaceStateEstimator
from backend.strategy.engine import StrategyConfig, StrategyDecisionType
from backend.strategy.estimator import StrategyEngineEstimator
from backend.tyre.estimator import TyreDegradationEstimator
from simulator.generator.core import FlagPeriod, GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig


def test_injected_safety_car_triggers_event_and_immediate_strategy_reassessment():
    total_laps = 15
    config = GeneratorConfig(
        laps=total_laps,
        noise=NoiseConfig.moderate(),
        flag_periods=(FlagPeriod(start_lap=8, end_lap=10, kind="SC"),),
    )
    frames = list(TelemetryGenerator(config, seed=21).frames())

    pipeline = default_pipeline()
    race_state_estimator = RaceStateEstimator()
    tyre_estimator = TyreDegradationEstimator()
    pace_estimator = PaceIntelligenceEstimator()
    strategy_estimator = StrategyEngineEstimator(StrategyConfig(race_total_laps=total_laps))
    event_engine = EventDetectionEngine()

    safety_car_events = []
    strategy_decisions_by_lap: dict[int, str] = {}
    reassessed_immediately_on_sc = False

    for frame in frames:
        result = pipeline.process(frame)
        state = race_state_estimator.update(result)
        if state is None:
            continue

        tyre_estimator.update(state)
        pace_estimator.update(state, tyre_estimator=tyre_estimator)

        pre_decision_id = id(state.current_strategy)
        strategy_estimator.update(state, tyre_estimator, pace_estimator)
        post_decision_id = id(state.current_strategy)

        events = event_engine.detect(state)
        for event in events:
            if event.event_type == EventType.SAFETY_CAR:
                safety_car_events.append(event)
                if pre_decision_id != post_decision_id:
                    reassessed_immediately_on_sc = True

        strategy_decisions_by_lap[state.current_lap] = state.current_strategy.decision.value

    assert len(safety_car_events) == 1  # fires once, on the rising edge, not once per frame
    assert safety_car_events[0].lap == 8
    assert reassessed_immediately_on_sc, "strategy must reassess the SAME frame the SC flag rises, not wait for lap completion"

    for lap in range(8, 11):
        assert strategy_decisions_by_lap.get(lap) in [d.value for d in StrategyDecisionType]
