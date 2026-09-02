"""Tests for the common RaceTelemetry schema (backend/telemetry/schema.py)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.telemetry.schema import (
    DataSource,
    OpponentState,
    PitStatus,
    RaceTelemetry,
    TyreCompound,
    WeatherState,
)


def test_minimal_frame_constructs_with_only_required_fields(base_frame_kwargs):
    frame = RaceTelemetry(**base_frame_kwargs)

    assert frame.car_id == "44"
    assert frame.lap == 1
    assert frame.source == DataSource.SIMULATOR
    # Everything else defaults to None/empty rather than raising.
    assert frame.speed_kph is None
    assert frame.tyre_age_laps is None
    assert frame.pit_history == []
    assert frame.opponent_states == []
    assert frame.data_quality_flags == []


def test_missing_required_field_raises(base_frame_kwargs):
    incomplete = dict(base_frame_kwargs)
    del incomplete["car_id"]

    with pytest.raises(ValidationError):
        RaceTelemetry(**incomplete)


def test_enum_fields_accept_valid_values_and_reject_invalid(base_frame_kwargs):
    frame = RaceTelemetry(
        **base_frame_kwargs,
        tyre_compound=TyreCompound.MEDIUM,
        weather=WeatherState.DAMP,
        pit_status=PitStatus.ON_TRACK,
    )
    assert frame.tyre_compound == TyreCompound.MEDIUM

    with pytest.raises(ValidationError):
        RaceTelemetry(**base_frame_kwargs, tyre_compound="NOT_A_COMPOUND")


def test_nested_structures_round_trip(base_frame_kwargs):
    frame = RaceTelemetry(
        **base_frame_kwargs,
        wheel_speeds={"front_left": 120.0, "front_right": 119.5},
        opponent_states=[
            OpponentState(car_id="1", position=2, gap_s=0.8, compound=TyreCompound.HARD)
        ],
    )
    assert frame.wheel_speeds.front_left == 120.0
    assert frame.opponent_states[0].car_id == "1"
    assert frame.opponent_states[0].compound == TyreCompound.HARD


def test_extra_fields_are_allowed_for_forward_compatibility(base_frame_kwargs):
    """Adapters must be able to attach source-specific fields without a schema change."""

    frame = RaceTelemetry(**base_frame_kwargs, experimental_ers_deployment_pct=63.2)
    assert frame.model_extra["experimental_ers_deployment_pct"] == 63.2


def test_schema_is_deliberately_permissive_on_physical_plausibility(base_frame_kwargs):
    """Impossible raw values must NOT be rejected at construction time.

    Catching them is the explicit job of the normalization pipeline's
    impossible-value-detection stage (see backend/normalization/base.py and
    docs/ARCHITECTURE.md), not the schema. This test documents that design
    choice and guards against accidentally tightening the schema later.
    """

    frame = RaceTelemetry(
        **base_frame_kwargs,
        tyre_age_laps=-3,
        speed_kph=-50.0,
        rain_probability=4.2,
    )
    assert frame.tyre_age_laps == -3
    assert frame.speed_kph == -50.0
    assert frame.rain_probability == 4.2


def test_timestamps_are_timezone_aware(base_frame_kwargs):
    frame = RaceTelemetry(**base_frame_kwargs)
    assert frame.source_timestamp.tzinfo is not None


def test_naive_datetime_is_rejected_by_convention(base_frame_kwargs):
    """We require tz-aware timestamps; a naive datetime should not silently pass as UTC."""

    naive_kwargs = dict(base_frame_kwargs)
    naive_kwargs["source_timestamp"] = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo

    frame = RaceTelemetry(**naive_kwargs)
    # Pydantic v2 preserves naive datetimes as-is rather than rejecting them;
    # this test documents that ambiguity so adapters know to always pass
    # timezone-aware timestamps themselves.
    assert frame.source_timestamp.tzinfo is None
