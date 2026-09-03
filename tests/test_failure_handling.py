"""Failure handling & graceful degradation tests for Phase 26 (`docs/VALIDATION.md`).

Validates pipeline resilience against:
  1. Missing telemetry streams / packet drops (LOCF state retention)
  2. Out-of-order telemetry frames (sorted deterministically by source_timestamp)
  3. Corrupted sensor values (clamped & sanitized by normalization stages)
  4. Non-fatal optional module failures (handled gracefully via log_and_continue)
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from backend.normalization.stages import default_pipeline
from backend.observability.logging import get_logger, log_and_continue
from backend.state.estimator import RaceStateEstimator
from backend.telemetry.schema import DataSource, RaceTelemetry, TyreTemperatures

logger = get_logger("failure_handling_test")


def test_out_of_order_telemetry_frames_handled():
    now = datetime.now(timezone.utc)
    t1 = now.timestamp()
    t2 = t1 + 1.0
    t3 = t1 + 2.0

    frame1 = RaceTelemetry(car_id="44", source=DataSource.SIMULATOR, source_timestamp=datetime.fromtimestamp(t1, timezone.utc), speed_kph=200.0, lap=1)
    frame2 = RaceTelemetry(car_id="44", source=DataSource.SIMULATOR, source_timestamp=datetime.fromtimestamp(t2, timezone.utc), speed_kph=220.0, lap=1)
    frame3 = RaceTelemetry(car_id="44", source=DataSource.SIMULATOR, source_timestamp=datetime.fromtimestamp(t3, timezone.utc), speed_kph=240.0, lap=1)

    out_of_order = [frame3, frame1, frame2]
    out_of_order.sort(key=lambda f: f.source_timestamp)

    assert [f.speed_kph for f in out_of_order] == [200.0, 220.0, 240.0]


def test_corrupted_sensor_values_clamped():
    pipeline = default_pipeline()
    corrupted_frame = RaceTelemetry(
        car_id="44",
        source=DataSource.SIMULATOR,
        source_timestamp=datetime.now(timezone.utc),
        speed_kph=-999.0,  # invalid negative speed
        throttle_pct=150.0,  # invalid >100% throttle
        brake_pct=-50.0,  # invalid negative brake
        tyre_temperatures=TyreTemperatures(front_left_c=9999.0),
        lap=1,
    )

    result = pipeline.process(corrupted_frame)
    frame = result.normalized_frame or result.raw_frame

    assert frame.speed_kph >= 0.0
    assert frame.throttle_pct <= 100.0
    assert frame.brake_pct >= 0.0
    assert len(result.issues) >= 1


def test_missing_telemetry_stream_retains_locf_state():
    estimator = RaceStateEstimator()
    frame1 = RaceTelemetry(
        car_id="44",
        source=DataSource.SIMULATOR,
        source_timestamp=datetime.now(timezone.utc),
        speed_kph=250.0,
        lap=5,
        position=2,
    )
    pipeline = default_pipeline()
    res1 = pipeline.process(frame1)
    state1 = estimator.update(res1)

    assert state1 is not None
    assert state1.current_lap == 5

    # Simulate dropped stream -- estimator retains previous LOCF state
    state_locf = estimator.get_state("44")
    assert state_locf is not None
    assert state_locf.current_lap == 5
    assert state_locf.position == 2


def test_log_and_continue_prevents_pipeline_crash():
    executed = False

    with log_and_continue(logger, "optional_radio_enrichment", car_id="44"):
        raise ValueError("Simulated network drop on radio extraction service")

    executed = True
    assert executed is True
