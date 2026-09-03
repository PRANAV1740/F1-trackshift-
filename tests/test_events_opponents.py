"""Tests for the opponent-aware event detectors added in Phase 14
(backend/events/detector.py::EventDetectionEngine._detect_opponent_events).
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.events.detector import DetectionThresholds, EventDetectionEngine
from backend.events.model import EventType
from backend.opponents.model import OpponentSummary, ThreatLevel
from backend.state.race_state import RaceState
from backend.telemetry.schema import PitStatus, TyreCompound

BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _state(**overrides) -> RaceState:
    state = RaceState(car_id="44", current_lap=5, last_updated=BASE_TS)
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


def _summary(is_ahead, gap=2.0, pit_probability=0.1, pit_status=None):
    return OpponentSummary(
        car_id="1", position=1 if is_ahead else 2, compound=TyreCompound.MEDIUM, tyre_age_laps=10,
        current_pace_s=90.0, degradation_rate_s_per_lap=0.03, pit_probability=pit_probability,
        pit_status=pit_status, gap_magnitude_s=gap, is_ahead=is_ahead,
        undercut_threat=ThreatLevel.NONE, overcut_threat=ThreatLevel.NONE,
    )


def test_opponent_pitting_fires_on_entering_pit_transition():
    engine = EventDetectionEngine()
    # Far gap so this scenario isolates ONLY the pit-status transition --
    # a close ahead opponent would legitimately also trigger
    # UNDERCUT_OPPORTUNITY/POSITION_OPPORTUNITY at the same time (those are
    # independent, non-exclusive signals; see the two tests below).
    state = _state(opponent_threats={"1": _summary(is_ahead=True, gap=30.0, pit_status=None)})
    assert engine.detect(state) == []

    state.opponent_threats = {"1": _summary(is_ahead=True, gap=30.0, pit_status=PitStatus.ENTERING_PIT)}
    events = engine.detect(state)
    assert len(events) == 1
    assert events[0].event_type == EventType.OPPONENT_PITTING

    # held in the pit box next frame -- must not re-fire
    state.opponent_threats = {"1": _summary(is_ahead=True, gap=30.0, pit_status=PitStatus.IN_PIT_BOX)}
    assert engine.detect(state) == []


def test_undercut_opportunity_fires_when_close_ahead_opponent_not_about_to_pit():
    """A close ahead opponent also legitimately trips POSITION_OPPORTUNITY
    at the same time -- that's a real, independent signal (a close rival
    ahead is always a passing opportunity regardless of their pit
    likelihood), not a conflict with UNDERCUT_OPPORTUNITY."""

    engine = EventDetectionEngine(DetectionThresholds(battle_gap_s=3.0, opponent_pit_probability_uncommitted=0.25))
    state = _state(opponent_threats={"1": _summary(is_ahead=True, gap=1.5, pit_probability=0.1)})

    events = engine.detect(state)
    event_types = {e.event_type for e in events}
    assert EventType.UNDERCUT_OPPORTUNITY in event_types
    assert EventType.POSITION_OPPORTUNITY in event_types

    # still true next frame -- must not re-fire either one
    assert engine.detect(state) == []


def test_overcut_opportunity_fires_when_opponent_about_to_pit_and_we_are_not():
    engine = EventDetectionEngine(
        DetectionThresholds(battle_gap_s=3.0, opponent_pit_probability_committed=0.6, opponent_pit_probability_uncommitted=0.25)
    )
    state = _state(
        opponent_threats={"1": _summary(is_ahead=True, gap=1.5, pit_probability=0.8)},
        tyre_cliff_probability=0.05,  # our own pit probability is low
    )

    events = engine.detect(state)
    assert EventType.OVERCUT_OPPORTUNITY in {e.event_type for e in events}


def test_undercut_and_overcut_do_not_apply_to_an_opponent_behind():
    engine = EventDetectionEngine()
    state = _state(opponent_threats={"1": _summary(is_ahead=False, gap=1.0, pit_probability=0.1)})
    events = engine.detect(state)
    assert all(e.event_type not in (EventType.UNDERCUT_OPPORTUNITY, EventType.OVERCUT_OPPORTUNITY) for e in events)


def test_position_threat_fires_for_close_opponent_behind():
    engine = EventDetectionEngine(DetectionThresholds(battle_gap_s=3.0))
    state = _state(opponent_threats={"1": _summary(is_ahead=False, gap=1.0)})

    events = engine.detect(state)
    assert len(events) == 1
    assert events[0].event_type == EventType.POSITION_THREAT


def test_position_opportunity_fires_for_close_opponent_ahead():
    engine = EventDetectionEngine(DetectionThresholds(battle_gap_s=3.0))
    state = _state(opponent_threats={"1": _summary(is_ahead=True, gap=1.0, pit_probability=0.5)})

    events = engine.detect(state)
    assert any(e.event_type == EventType.POSITION_OPPORTUNITY for e in events)


def test_no_events_for_a_distant_opponent():
    engine = EventDetectionEngine(DetectionThresholds(battle_gap_s=3.0))
    state = _state(opponent_threats={"1": _summary(is_ahead=True, gap=30.0, pit_probability=0.5)})
    events = engine.detect(state)
    assert events == []


def test_traffic_release_fires_when_gap_ahead_opens_up_after_being_close():
    engine = EventDetectionEngine(DetectionThresholds(traffic_gap_s=1.5, traffic_release_gap_s=4.0))
    state = _state(opponent_threats={"1": _summary(is_ahead=True, gap=1.0, pit_probability=0.5)})
    engine.detect(state)  # establishes "in traffic" memory

    state.opponent_threats = {"1": _summary(is_ahead=True, gap=5.0, pit_probability=0.5)}
    events = engine.detect(state)
    assert any(e.event_type == EventType.TRAFFIC_RELEASE for e in events)


def test_traffic_release_does_not_fire_without_prior_traffic():
    engine = EventDetectionEngine(DetectionThresholds(traffic_gap_s=1.5, traffic_release_gap_s=4.0))
    state = _state(opponent_threats={"1": _summary(is_ahead=True, gap=5.0, pit_probability=0.5)})
    events = engine.detect(state)
    assert all(e.event_type != EventType.TRAFFIC_RELEASE for e in events)


def test_memory_is_dropped_for_opponents_no_longer_tracked():
    engine = EventDetectionEngine(DetectionThresholds(battle_gap_s=3.0))
    state = _state(opponent_threats={"1": _summary(is_ahead=False, gap=1.0)})
    engine.detect(state)

    mem = engine._memory["44"]
    assert "1" in mem.position_threat_active

    state.opponent_threats = {}  # opponent no longer tracked (e.g. lapped out of range)
    engine.detect(state)
    assert "1" not in mem.position_threat_active
