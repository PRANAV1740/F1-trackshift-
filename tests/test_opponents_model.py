"""Tests for backend/opponents/model.py."""

from __future__ import annotations

import pytest

from backend.opponents.model import ThreatLevel, pit_probability, summarize_opponent
from backend.state.race_state import RaceState
from backend.telemetry.schema import TyreCompound


def _state(car_id="1", cliff_prob=None, remaining_life=None, compound=TyreCompound.MEDIUM, pace=90.0, degradation_rate=0.03):
    state = RaceState(car_id=car_id, current_lap=10)
    state.tyre_cliff_probability = cliff_prob
    state.remaining_tyre_life_laps = remaining_life
    state.tyre_compound = compound
    state.current_pace_s = pace
    state.degradation_rate_s_per_lap = degradation_rate
    return state


def test_pit_probability_prefers_cliff_probability_when_available():
    state = _state(cliff_prob=0.8, remaining_life=20)
    assert pit_probability(state) == 0.8


def test_pit_probability_falls_back_to_remaining_life():
    state = _state(cliff_prob=None, remaining_life=5)
    assert pit_probability(state) == pytest.approx(1.0 - 5 / 15)


def test_pit_probability_none_with_no_data():
    state = _state(cliff_prob=None, remaining_life=None)
    assert pit_probability(state) is None


def test_undercut_threat_high_when_close_and_opponent_likely_to_pit():
    own = _state("44")
    opponent_behind = _state("1", cliff_prob=0.7)

    summary = summarize_opponent(own, opponent_behind, gap_magnitude_s=2.0, is_ahead=False)

    assert summary.undercut_threat == ThreatLevel.HIGH
    assert summary.overcut_threat == ThreatLevel.NONE  # not applicable when opponent is behind
    assert summary.is_ahead is False


def test_undercut_threat_low_when_far_even_if_opponent_likely_to_pit():
    own = _state("44")
    opponent_behind = _state("1", cliff_prob=0.9)

    summary = summarize_opponent(own, opponent_behind, gap_magnitude_s=20.0, is_ahead=False)

    assert summary.undercut_threat == ThreatLevel.LOW


def test_overcut_threat_high_when_we_are_under_pit_pressure_and_opponent_close_ahead():
    own = _state("44", cliff_prob=0.8)
    opponent_ahead = _state("1")

    summary = summarize_opponent(own, opponent_ahead, gap_magnitude_s=2.0, is_ahead=True)

    assert summary.overcut_threat == ThreatLevel.HIGH
    assert summary.undercut_threat == ThreatLevel.NONE  # not applicable when opponent is ahead


def test_threat_none_when_gap_or_pit_probability_unknown():
    own = _state("44")
    opponent = _state("1", cliff_prob=None, remaining_life=None)
    summary = summarize_opponent(own, opponent, gap_magnitude_s=None, is_ahead=False)
    assert summary.undercut_threat == ThreatLevel.NONE


def test_summary_carries_opponent_own_computed_fields_directly():
    own = _state("44")
    opponent = _state("1", compound=TyreCompound.HARD, pace=88.5, degradation_rate=0.015)

    summary = summarize_opponent(own, opponent, gap_magnitude_s=5.0, is_ahead=True)

    assert summary.compound == TyreCompound.HARD
    assert summary.current_pace_s == 88.5
    assert summary.degradation_rate_s_per_lap == 0.015
