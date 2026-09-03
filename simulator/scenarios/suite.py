"""Scenario suite implementation.

Factory and catalog for all 12 named, seeded scenarios required by Phase 19:
1. normal_race
2. tyre_cliff
3. vsc_pit_opportunity
4. sc_pit_opportunity
5. opponent_undercut
6. opponent_overcut
7. rain_arrival
8. heavy_traffic
9. telemetry_corruption
10. missing_telemetry
11. strategy_inferiority
12. driver_disagreement
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from backend.adapters.simulator_adapter import SimulatorAdapter
from backend.events.detector import EventDetectionEngine
from backend.events.model import RaceEvent
from backend.ingestion.service import IngestionService
from backend.normalization.stages import default_pipeline
from backend.opponents.estimator import OpponentIntelligenceEstimator
from backend.opponents.order import RaceOrderTracker
from backend.pace.estimator import PaceIntelligenceEstimator
from backend.prediction.estimator import PositionPredictionEstimator
from backend.racing_line.estimator import RacingLineEstimator
from backend.state.estimator import RaceStateEstimator
from backend.state.race_state import RaceState
from backend.strategy.engine import StrategyConfig, decide
from backend.telemetry.schema import PitStatus, TrackState, TyreCompound, WeatherState
from backend.tyre.estimator import TyreDegradationEstimator
from radio.disagreement import HumanAIDisagreementDetector
from radio.extraction.extractor import RadioIntentExtractor
from radio.model import DriverRadioMessage, RadioIntent
from simulator.generator.core import FlagPeriod, GeneratorConfig, PitStopEvent, TelemetryGenerator, WeatherTransition
from simulator.generator.noise import NoiseConfig
from simulator.scenarios.model import ScenarioDefinition

BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

NAMED_SCENARIOS = (
    "normal_race",
    "tyre_cliff",
    "vsc_pit_opportunity",
    "sc_pit_opportunity",
    "opponent_undercut",
    "opponent_overcut",
    "rain_arrival",
    "heavy_traffic",
    "telemetry_corruption",
    "missing_telemetry",
    "strategy_inferiority",
    "driver_disagreement",
)


def create_scenario(scenario_id: str, seed: int = 42) -> ScenarioDefinition:
    """Factory creating deterministic `ScenarioDefinition` for a given scenario_id and seed."""

    if scenario_id not in NAMED_SCENARIOS:
        raise ValueError(f"Unknown scenario_id '{scenario_id}'. Available: {NAMED_SCENARIOS}")

    if scenario_id == "normal_race":
        cfg = GeneratorConfig(
            car_id="44",
            laps=20,
            compound=TyreCompound.MEDIUM,
            noise=NoiseConfig.clean(),
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Normal Race",
            description="Clean 20-lap stint under green flag conditions.",
            seed=seed,
            generator_configs={"44": cfg},
        )

    elif scenario_id == "tyre_cliff":
        cfg = GeneratorConfig(
            car_id="44",
            laps=22,
            compound=TyreCompound.SOFT,
            noise=NoiseConfig.clean(),
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Tyre Cliff",
            description="Stint on SOFT tyres hitting cliff near lap 16.",
            seed=seed,
            generator_configs={"44": cfg},
        )

    elif scenario_id == "vsc_pit_opportunity":
        cfg = GeneratorConfig(
            car_id="44",
            laps=20,
            compound=TyreCompound.MEDIUM,
            noise=NoiseConfig.clean(),
            flag_periods=(FlagPeriod(start_lap=10, end_lap=12, kind="VSC"),),
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="VSC Pit Opportunity",
            description="Virtual Safety Car deployed laps 10-12 reducing pit loss.",
            seed=seed,
            generator_configs={"44": cfg},
        )

    elif scenario_id == "sc_pit_opportunity":
        cfg = GeneratorConfig(
            car_id="44",
            laps=20,
            compound=TyreCompound.MEDIUM,
            noise=NoiseConfig.clean(),
            flag_periods=(FlagPeriod(start_lap=12, end_lap=15, kind="SC"),),
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Safety Car Pit Opportunity",
            description="Full Safety Car deployed laps 12-15.",
            seed=seed,
            generator_configs={"44": cfg},
        )

    elif scenario_id == "opponent_undercut":
        cfg_us = GeneratorConfig(car_id="44", laps=15, compound=TyreCompound.MEDIUM, starting_fuel_kg=105.0)
        cfg_rival = GeneratorConfig(car_id="1", laps=15, compound=TyreCompound.MEDIUM, starting_fuel_kg=100.0)
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Opponent Undercut",
            description="Rival ahead with low pit probability; opportunity to undercut.",
            seed=seed,
            generator_configs={"44": cfg_us, "1": cfg_rival},
        )

    elif scenario_id == "opponent_overcut":
        cfg_us = GeneratorConfig(car_id="44", laps=15, compound=TyreCompound.MEDIUM, starting_fuel_kg=100.0)
        cfg_rival = GeneratorConfig(
            car_id="1",
            laps=15,
            compound=TyreCompound.SOFT,
            starting_fuel_kg=105.0,
            pit_stops=(PitStopEvent(lap=10, new_compound=TyreCompound.HARD),),
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Opponent Overcut",
            description="Rival ahead pitting early; opportunity to extend and overcut.",
            seed=seed,
            generator_configs={"44": cfg_us, "1": cfg_rival},
        )

    elif scenario_id == "rain_arrival":
        cfg = GeneratorConfig(
            car_id="44",
            laps=20,
            compound=TyreCompound.MEDIUM,
            weather_transitions=(
                WeatherTransition(start_lap=8, weather=WeatherState.WET, rain_probability=0.85),
            ),
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Rain Arrival",
            description="Rain arrives at lap 8, driving weather transition.",
            seed=seed,
            generator_configs={"44": cfg},
        )

    elif scenario_id == "heavy_traffic":
        cfg_us = GeneratorConfig(car_id="44", laps=15, compound=TyreCompound.MEDIUM, starting_fuel_kg=100.0)
        cfg_slow = GeneratorConfig(car_id="55", laps=15, compound=TyreCompound.HARD, starting_fuel_kg=110.0, v_max_kph=300.0)
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Heavy Traffic",
            description="Stuck behind slower car in dirty air.",
            seed=seed,
            generator_configs={"44": cfg_us, "55": cfg_slow},
        )

    elif scenario_id == "telemetry_corruption":
        cfg = GeneratorConfig(
            car_id="44",
            laps=15,
            compound=TyreCompound.MEDIUM,
            noise=NoiseConfig.severe(),
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Telemetry Corruption",
            description="Severe sensor noise, dropped packets, and duplicates.",
            seed=seed,
            generator_configs={"44": cfg},
        )

    elif scenario_id == "missing_telemetry":
        cfg = GeneratorConfig(
            car_id="44",
            laps=15,
            compound=TyreCompound.MEDIUM,
            noise=NoiseConfig(missing_packet_probability=0.3, spike_probability=0.1),
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Missing Telemetry",
            description="High packet drop rate testing LOCF missing data handling.",
            seed=seed,
            generator_configs={"44": cfg},
        )

    elif scenario_id == "strategy_inferiority":
        cfg = GeneratorConfig(
            car_id="44",
            laps=25,
            compound=TyreCompound.SOFT,
            noise=NoiseConfig.clean(),
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Strategy Inferiority",
            description="Baseline naive stay-out strategy vs AI timely pit strategy.",
            seed=seed,
            generator_configs={"44": cfg},
        )

    elif scenario_id == "driver_disagreement":
        cfg = GeneratorConfig(
            car_id="44",
            laps=15,
            compound=TyreCompound.MEDIUM,
            noise=NoiseConfig.clean(),
        )
        msg = DriverRadioMessage(
            message_id="msg_demo1",
            car_id="44",
            lap=10,
            timestamp=BASE_TS,
            speaker="DRIVER",
            raw_text="Tyres are completely destroyed, I need to pit right now!",
            detected_intents=[RadioIntent.TYRE_GRAINING, RadioIntent.STRATEGY_PIT_REQUEST],
            is_demo_mode=True,
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name="Driver Disagreement",
            description="Driver reports destroyed tyres while telemetry indicates low degradation.",
            seed=seed,
            generator_configs={"44": cfg},
            radio_messages=[msg],
        )

    raise ValueError(f"Unhandled scenario {scenario_id}")


class ScenarioRunner:
    """Executes a `ScenarioDefinition` end-to-end through the full intelligence pipeline."""

    def run(self, scenario: ScenarioDefinition) -> dict[str, RaceState]:
        pipeline = default_pipeline()
        race_state_estimator = RaceStateEstimator()
        tyre_estimator = TyreDegradationEstimator()
        pace_estimator = PaceIntelligenceEstimator()
        racing_line_estimator = RacingLineEstimator()
        order_tracker = RaceOrderTracker()
        opponent_estimator = OpponentIntelligenceEstimator(order_tracker)
        prediction_estimator = PositionPredictionEstimator()
        event_engine = EventDetectionEngine()
        disagreement_detector = HumanAIDisagreementDetector()

        # Collect frames for each car
        all_frames = []
        for car_id, cfg in scenario.generator_configs.items():
            gen_frames = list(TelemetryGenerator(cfg, seed=scenario.seed).frames())
            all_frames.extend(gen_frames)

        # Sort frames by source_timestamp
        all_frames.sort(key=lambda f: f.source_timestamp)

        for frame in all_frames:
            racing_line_estimator.process_frame(frame)
            res = pipeline.process(frame)
            state = race_state_estimator.update(res)
            if state is not None:
                tyre_estimator.update(state)
                pace_estimator.update(state)
                racing_line_estimator.update(state)

        # Final pass over all cars for opponent intelligence & prediction
        all_states = race_state_estimator.all_states()
        opponent_estimator.update_all(race_state_estimator)
        for car_id, state in all_states.items():
            prediction_estimator.update(state)

            # Evaluate strategy decision
            state.current_strategy = decide(state, tyre_estimator, pace_estimator, StrategyConfig())

            # Evaluate events
            events = event_engine.detect(state)

            # Evaluate radio & disagreements if radio messages exist
            for msg in scenario.radio_messages:
                if msg.car_id == car_id:
                    state.latest_radio_message = msg
                    state.radio_history.append(msg)
                    disagreements = disagreement_detector.evaluate_disagreement(state, msg)
                    state.disagreements.extend(disagreements)

        return all_states
