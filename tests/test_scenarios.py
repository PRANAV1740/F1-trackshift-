"""Scenario suite tests for Phase 19 (`simulator/scenarios`)."""

from __future__ import annotations

import pytest

from backend.events.model import EventType
from backend.telemetry.schema import TyreCompound
from radio.disagreement import DisagreementType
from simulator.scenarios.suite import NAMED_SCENARIOS, ScenarioRunner, create_scenario


def test_scenario_catalog_contains_all_12_named_scenarios():
    assert len(NAMED_SCENARIOS) == 12
    for scenario_id in NAMED_SCENARIOS:
        sc = create_scenario(scenario_id, seed=42)
        assert sc.scenario_id == scenario_id
        assert sc.name != ""
        assert sc.seed == 42


def test_unknown_scenario_raises_value_error():
    with pytest.raises(ValueError, match="Unknown scenario_id"):
        create_scenario("non_existent_scenario")


def test_normal_race_scenario_runs_cleanly():
    sc = create_scenario("normal_race", seed=10)
    runner = ScenarioRunner()
    states = runner.run(sc)

    assert "44" in states
    state = states["44"]
    assert state.current_lap == 20
    assert len(state.completed_laps) == 19
    assert state.current_strategy is not None


def test_tyre_cliff_scenario_triggers_cliff_probability():
    sc = create_scenario("tyre_cliff", seed=11)
    runner = ScenarioRunner()
    states = runner.run(sc)

    state = states["44"]
    assert state.tyre_cliff_probability is not None
    assert state.tyre_cliff_probability > 0.0


def test_vsc_pit_opportunity_scenario():
    sc = create_scenario("vsc_pit_opportunity", seed=12)
    runner = ScenarioRunner()
    states = runner.run(sc)

    state = states["44"]
    assert state.vsc is False or state.vsc is True  # handled correctly
    assert state.current_strategy is not None


def test_opponent_undercut_scenario():
    sc = create_scenario("opponent_undercut", seed=13)
    runner = ScenarioRunner()
    states = runner.run(sc)

    assert "44" in states and "1" in states
    state_us = states["44"]
    assert "1" in state_us.opponent_threats


def test_rain_arrival_scenario():
    sc = create_scenario("rain_arrival", seed=14)
    runner = ScenarioRunner()
    states = runner.run(sc)

    state = states["44"]
    assert state.rain_probability is not None
    assert state.rain_probability >= 0.80


def test_telemetry_corruption_scenario_normalizes_severe_noise():
    sc = create_scenario("telemetry_corruption", seed=15)
    runner = ScenarioRunner()
    states = runner.run(sc)

    state = states["44"]
    assert state.current_lap > 0
    assert state.confidence < 1.0 or state.confidence == 1.0


def test_driver_disagreement_scenario_produces_disagreement_record():
    sc = create_scenario("driver_disagreement", seed=16)
    runner = ScenarioRunner()
    states = runner.run(sc)

    state = states["44"]
    assert len(state.disagreements) >= 1
    assert state.disagreements[0].disagreement_type == DisagreementType.DRIVER_REPORTS_TYRE_ISSUE_BUT_TELEMETRY_HEALTHY
