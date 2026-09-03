"""Tests for Phase 25 Observability & Decision Audit Trail (`backend/observability/audit.py`)."""

from __future__ import annotations

import json
import pytest

from backend.observability.audit import DecisionAuditLogger, DecisionAuditRecord
from backend.state.race_state import RaceState, TyreCompound, WeatherState
from backend.strategy.engine import StrategyDecision, StrategyDecisionType


def test_decision_audit_logger_records_and_evaluates():
    logger = DecisionAuditLogger()

    # Lap 10 decision
    state_lap10 = RaceState(
        car_id="44",
        current_lap=10,
        position=2,
        tyre_compound=TyreCompound.MEDIUM,
        tyre_age_laps=10,
        estimated_degradation_s=0.04,
        tyre_cliff_probability=0.20,
        weather=WeatherState.DRY,
        gap_ahead_s=2.5,
        gap_behind_s=4.0,
    )
    state_lap10.current_strategy = StrategyDecision(
        car_id="44",
        lap=10,
        decision=StrategyDecisionType.STAY_OUT,
        compound=TyreCompound.HARD,
        window=(16, 18),
        confidence=0.88,
        expected_position=1,
        position_gain=1,
        reasons=["Clean air gap ahead", "Degradation rate linear", "Optimal pit window ahead"],
    )

    record = logger.log_decision(state_lap10)

    assert isinstance(record, DecisionAuditRecord)
    assert record.car_id == "44"
    assert record.lap == 10
    assert record.decision == "STAY_OUT"
    assert record.confidence == 0.88
    assert len(record.top_3_reasons) == 3
    assert len(record.invalidation_conditions) >= 3
    assert "tyre_model" in record.model_versions

    # Lap 12: Not yet +5 laps
    state_lap12 = RaceState(car_id="44", current_lap=12, position=2)
    eval_lap12 = logger.check_and_evaluate_outcomes(state_lap12)
    assert len(eval_lap12) == 0
    assert record.actual_outcome_lap_plus_5 is None

    # Lap 15: +5 laps reached!
    state_lap15 = RaceState(car_id="44", current_lap=15, position=1, gap_ahead_s=0.0)
    eval_lap15 = logger.check_and_evaluate_outcomes(state_lap15)
    assert len(eval_lap15) == 1
    evaluated_rec = eval_lap15[0]
    assert evaluated_rec.actual_outcome_lap_plus_5["actual_position"] == 1
    assert evaluated_rec.outcome_accuracy_error_s is not None

    # History & Export JSON
    history = logger.get_history("44")
    assert len(history) == 1

    json_str = logger.export_json()
    parsed = json.loads(json_str)
    assert len(parsed) == 1
    assert parsed[0]["decision"] == "STAY_OUT"
