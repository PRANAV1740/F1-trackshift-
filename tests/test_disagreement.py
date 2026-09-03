"""Tests for Phase 17 -- Human/AI Disagreement Detection (`radio/disagreement.py`)."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.state.race_state import RaceState
from backend.strategy.engine import StrategyDecision, StrategyDecisionType
from radio.disagreement import DisagreementType, HumanAIDisagreementDetector
from radio.extraction.extractor import RadioIntentExtractor
from radio.model import DriverRadioMessage, RadioIntent

BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_tyre_issue_reported_when_telemetry_healthy():
    detector = HumanAIDisagreementDetector()
    state = RaceState(
        car_id="44",
        current_lap=10,
        estimated_degradation_s=0.05,
        degradation_rate_s_per_lap=0.01,
        last_updated=BASE_TS,
    )
    msg = DriverRadioMessage(
        message_id="msg1",
        car_id="44",
        lap=10,
        timestamp=BASE_TS,
        speaker="DRIVER",
        raw_text="Front left is graining badly",
        detected_intents=[RadioIntent.TYRE_GRAINING],
    )

    disagreements = detector.evaluate_disagreement(state, msg)
    assert len(disagreements) == 1
    assert disagreements[0].disagreement_type == DisagreementType.DRIVER_REPORTS_TYRE_ISSUE_BUT_TELEMETRY_HEALTHY
    assert "graining" in disagreements[0].summary.lower()


def test_no_disagreement_when_driver_tyre_report_matches_high_degradation():
    detector = HumanAIDisagreementDetector()
    state = RaceState(
        car_id="44",
        current_lap=10,
        estimated_degradation_s=0.95,
        degradation_rate_s_per_lap=0.08,
        last_updated=BASE_TS,
    )
    msg = DriverRadioMessage(
        message_id="msg1",
        car_id="44",
        lap=10,
        timestamp=BASE_TS,
        speaker="DRIVER",
        raw_text="Front left is graining badly",
        detected_intents=[RadioIntent.TYRE_GRAINING],
    )

    disagreements = detector.evaluate_disagreement(state, msg)
    assert disagreements == []


def test_stay_out_reported_when_cliff_imminent():
    detector = HumanAIDisagreementDetector()
    state = RaceState(
        car_id="44",
        current_lap=18,
        tyre_cliff_probability=0.75,
        last_updated=BASE_TS,
    )
    msg = DriverRadioMessage(
        message_id="msg2",
        car_id="44",
        lap=18,
        timestamp=BASE_TS,
        speaker="DRIVER",
        raw_text="Tyres feel fine, stay out",
        detected_intents=[RadioIntent.STRATEGY_STAY_OUT_REQUEST],
    )

    disagreements = detector.evaluate_disagreement(state, msg)
    assert len(disagreements) == 1
    assert disagreements[0].disagreement_type == DisagreementType.DRIVER_REPORTS_TYRES_FINE_BUT_CLIFF_IMMINENT


def test_pit_request_when_strategy_recommends_stay_out():
    detector = HumanAIDisagreementDetector()
    state = RaceState(
        car_id="44",
        current_lap=12,
        last_updated=BASE_TS,
    )
    state.current_strategy = StrategyDecision(
        car_id="44",
        lap=12,
        decision=StrategyDecisionType.STAY_OUT,
        compound=None,
        window=None,
        confidence=0.85,
        expected_position=1,
        position_gain=0,
        reasons=["Pace remains competitive"],
    )
    msg = DriverRadioMessage(
        message_id="msg3",
        car_id="44",
        lap=12,
        timestamp=BASE_TS,
        speaker="DRIVER",
        raw_text="Box this lap",
        detected_intents=[RadioIntent.STRATEGY_PIT_REQUEST],
    )

    disagreements = detector.evaluate_disagreement(state, msg)
    assert len(disagreements) == 1
    assert disagreements[0].disagreement_type == DisagreementType.DRIVER_REQUESTS_PIT_BUT_STRATEGY_RECOMMENDS_STAY_OUT


def test_rain_reported_when_weather_sensors_dry():
    detector = HumanAIDisagreementDetector()
    state = RaceState(
        car_id="44",
        current_lap=5,
        rain_probability=0.02,
        last_updated=BASE_TS,
    )
    msg = DriverRadioMessage(
        message_id="msg4",
        car_id="44",
        lap=5,
        timestamp=BASE_TS,
        speaker="DRIVER",
        raw_text="Seeing rain drops in sector 2",
        detected_intents=[RadioIntent.RAIN_REPORTED],
    )

    disagreements = detector.evaluate_disagreement(state, msg)
    assert len(disagreements) == 1
    assert disagreements[0].disagreement_type == DisagreementType.DRIVER_REPORTS_RAIN_BUT_WEATHER_DRY


def test_traffic_reported_when_gap_ahead_is_large():
    detector = HumanAIDisagreementDetector()
    state = RaceState(
        car_id="44",
        current_lap=8,
        gap_ahead_s=5.5,
        last_updated=BASE_TS,
    )
    msg = DriverRadioMessage(
        message_id="msg5",
        car_id="44",
        lap=8,
        timestamp=BASE_TS,
        speaker="DRIVER",
        raw_text="Stuck in heavy traffic",
        detected_intents=[RadioIntent.TRAFFIC_HEAVY],
    )

    disagreements = detector.evaluate_disagreement(state, msg)
    assert len(disagreements) == 1
    assert disagreements[0].disagreement_type == DisagreementType.DRIVER_REPORTS_TRAFFIC_BUT_GAP_LARGE
