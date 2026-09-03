"""Tests for backend/opponents/order.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.opponents.order import RaceOrderTracker
from backend.state.race_state import RaceState
from backend.telemetry.schema import DataSource, RaceTelemetry

BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _state(car_id, lap, lap_start_offset_s, elapsed_into_lap_s, pace_s=90.0):
    lap_start = BASE_TS + timedelta(seconds=lap_start_offset_s)
    now = lap_start + timedelta(seconds=elapsed_into_lap_s)
    state = RaceState(car_id=car_id, current_lap=lap, current_lap_start_ts=lap_start, current_pace_s=pace_s)
    state.latest_frame = RaceTelemetry(source=DataSource.SIMULATOR, source_timestamp=now, car_id=car_id, lap=lap)
    return state


def test_leader_is_the_car_with_more_progress():
    tracker = RaceOrderTracker()
    leader = _state("44", lap=5, lap_start_offset_s=0, elapsed_into_lap_s=60.0)  # 2/3 through lap 5
    chaser = _state("1", lap=5, lap_start_offset_s=0, elapsed_into_lap_s=10.0)  # just started lap 5

    tracker.update(leader)
    tracker.update(chaser)
    order = tracker.order()

    assert [p.car_id for p in order] == ["44", "1"]


def test_apply_sets_position_and_gaps_for_two_cars():
    tracker = RaceOrderTracker()
    leader = _state("44", lap=5, lap_start_offset_s=0, elapsed_into_lap_s=60.0, pace_s=90.0)
    chaser = _state("1", lap=5, lap_start_offset_s=0, elapsed_into_lap_s=10.0, pace_s=90.0)
    states = {"44": leader, "1": chaser}

    tracker.update(leader)
    tracker.update(chaser)
    tracker.apply(states)

    assert leader.position == 1
    assert chaser.position == 2
    assert leader.gap_ahead_s is None
    assert chaser.gap_behind_s is None
    assert chaser.gap_ahead_s == pytest.approx(50.0, abs=0.5)  # leader is ~50s further into the lap
    assert leader.gap_behind_s == pytest.approx(50.0, abs=0.5)


def test_gap_seconds_works_for_non_adjacent_cars():
    tracker = RaceOrderTracker()
    a = _state("44", lap=5, lap_start_offset_s=0, elapsed_into_lap_s=80.0)
    b = _state("1", lap=5, lap_start_offset_s=0, elapsed_into_lap_s=40.0)
    c = _state("16", lap=5, lap_start_offset_s=0, elapsed_into_lap_s=0.0)

    for s in (a, b, c):
        tracker.update(s)

    gap_a_to_c = tracker.gap_seconds("44", "16")
    assert gap_a_to_c is not None
    assert gap_a_to_c < 0  # "16" is behind "44"
    assert abs(gap_a_to_c) == pytest.approx(80.0, abs=0.5)


def test_gap_seconds_returns_none_for_unknown_car():
    tracker = RaceOrderTracker()
    tracker.update(_state("44", lap=1, lap_start_offset_s=0, elapsed_into_lap_s=0))
    assert tracker.gap_seconds("44", "unknown") is None


def test_single_car_has_no_gaps():
    tracker = RaceOrderTracker()
    only = _state("44", lap=1, lap_start_offset_s=0, elapsed_into_lap_s=0)
    tracker.update(only)
    tracker.apply({"44": only})

    assert only.position == 1
    assert only.gap_ahead_s is None
    assert only.gap_behind_s is None
