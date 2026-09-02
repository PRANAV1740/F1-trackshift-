"""Tests for the concrete normalization stages (backend/normalization/stages.py).

One focused unit test per stage/failure class named in the Phase 3
requirements (missing packets, timestamp jitter, impossible speeds,
negative tyre age, temperature spikes, NaN values, duplicated telemetry,
noisy steering/braking), plus an end-to-end test running the full
`default_pipeline()` against severe simulator noise.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from backend.normalization.base import (
    NormalizationContext,
    NormalizationIssueSeverity,
    NormalizationPipeline,
    NormalizationRunLog,
)
from backend.normalization.stages import (
    DuplicateDetectionStage,
    FeatureExtractionStage,
    ImpossibleValueDetectionStage,
    MissingDataHandlingStage,
    SchemaValidationStage,
    SensorConfidenceScoringStage,
    SmoothingStage,
    SpikeDetectionStage,
    TimestampAlignmentStage,
    UnitNormalizationStage,
    default_pipeline,
)
from backend.telemetry.schema import RaceTelemetry, TyreTemperatures
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig

BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _frame(**overrides) -> RaceTelemetry:
    defaults = dict(source="SIMULATOR", source_timestamp=BASE_TS, car_id="44", lap=1)
    defaults.update(overrides)
    return RaceTelemetry(**defaults)


def _ctx(**overrides) -> NormalizationContext:
    return NormalizationContext(car_id="44", **overrides)


def _log() -> NormalizationRunLog:
    return NormalizationRunLog()


# --- SchemaValidationStage (NaN/Inf) -----------------------------------------


def test_schema_validation_replaces_nan_with_none():
    stage = SchemaValidationStage()
    frame = _frame(speed_kph=float("nan"), brake_pct=float("inf"))
    log = _log()

    result = stage.process(frame, _ctx(), log)

    assert result.speed_kph is None
    assert result.brake_pct is None
    assert len(log.changes) == 2
    assert any(i.severity.value == "ERROR" for i in log.issues)


def test_schema_validation_leaves_clean_frame_untouched():
    stage = SchemaValidationStage()
    frame = _frame(speed_kph=200.0)
    log = _log()

    result = stage.process(frame, _ctx(), log)

    assert result.speed_kph == 200.0
    assert log.changes == []


# --- UnitNormalizationStage ---------------------------------------------------


def test_unit_normalization_converts_speed_ms_extra_field():
    stage = UnitNormalizationStage()
    frame = _frame(speed_ms=50.0)  # extra field, no speed_kph
    log = _log()

    result = stage.process(frame, _ctx(), log)

    assert result.speed_kph == pytest.approx(180.0)
    assert len(log.changes) == 1


# --- TimestampAlignmentStage (jitter) -----------------------------------------


def test_timestamp_alignment_corrects_non_monotonic_timestamp():
    stage = TimestampAlignmentStage()
    prev = _frame(source_timestamp=BASE_TS)
    jittered = _frame(source_timestamp=BASE_TS - timedelta(milliseconds=50))
    log = _log()

    result = stage.process(jittered, _ctx(previous_frame=prev), log)

    assert result.source_timestamp > prev.source_timestamp
    assert len(log.changes) == 1


def test_timestamp_alignment_leaves_monotonic_timestamp_alone():
    stage = TimestampAlignmentStage()
    prev = _frame(source_timestamp=BASE_TS)
    ok = _frame(source_timestamp=BASE_TS + timedelta(milliseconds=200))
    log = _log()

    result = stage.process(ok, _ctx(previous_frame=prev), log)

    assert result.source_timestamp == ok.source_timestamp
    assert log.changes == []


# --- DuplicateDetectionStage ---------------------------------------------------


def test_duplicate_detection_drops_repeated_sequence_id():
    stage = DuplicateDetectionStage()
    prev = _frame(sequence_id=5)
    dup = _frame(sequence_id=5)
    log = _log()

    result = stage.process(dup, _ctx(previous_frame=prev), log)

    assert result is None
    assert len(log.issues) == 1


def test_duplicate_detection_falls_back_to_content_comparison_without_sequence_id():
    stage = DuplicateDetectionStage()
    prev = _frame(speed_kph=200.0)
    dup = _frame(speed_kph=200.0)
    distinct = _frame(speed_kph=201.0)
    log = _log()

    assert stage.process(dup, _ctx(previous_frame=prev), log) is None
    assert stage.process(distinct, _ctx(previous_frame=prev), _log()) is not None


# --- MissingDataHandlingStage (missing packets / LOCF) ------------------------


def test_missing_data_carries_forward_previous_speed():
    stage = MissingDataHandlingStage()
    prev = _frame(speed_kph=250.0)
    missing = _frame(speed_kph=None)
    log = _log()

    result = stage.process(missing, _ctx(previous_frame=prev), log)

    assert result.speed_kph == 250.0
    assert "INTERPOLATED:speed_kph" in result.data_quality_flags
    assert len(log.changes) == 1


def test_missing_data_with_no_prior_value_logs_warning_but_does_not_crash():
    """With no previous frame, every missing LOCF-eligible field (all of
    them are None by default on a bare _frame()) gets its own warning --
    none of them crash, and none get a fabricated value."""

    stage = MissingDataHandlingStage()
    missing = _frame()
    log = _log()

    result = stage.process(missing, _ctx(), log)

    assert result.speed_kph is None
    assert any(i.field == "speed_kph" for i in log.issues)
    assert all(i.severity == NormalizationIssueSeverity.WARNING for i in log.issues)


# --- ImpossibleValueDetectionStage (negative tyre age, impossible speed) ----


def test_impossible_value_clamps_negative_tyre_age():
    stage = ImpossibleValueDetectionStage()
    frame = _frame(tyre_age_laps=-5)
    log = _log()

    result = stage.process(frame, _ctx(), log)

    assert result.tyre_age_laps == 0
    assert "IMPOSSIBLE_VALUE:tyre_age_laps" in result.data_quality_flags


def test_impossible_value_clamps_impossible_speed():
    stage = ImpossibleValueDetectionStage()
    frame = _frame(speed_kph=900.0)
    log = _log()

    result = stage.process(frame, _ctx(), log)

    assert result.speed_kph == 400.0
    assert any(c.field == "speed_kph" for c in log.changes)


def test_impossible_value_leaves_plausible_values_alone():
    stage = ImpossibleValueDetectionStage()
    frame = _frame(speed_kph=300.0, tyre_age_laps=10)
    log = _log()

    result = stage.process(frame, _ctx(), log)

    assert result.speed_kph == 300.0
    assert result.tyre_age_laps == 10
    assert log.changes == []


# --- SpikeDetectionStage (temperature spikes) --------------------------------


def test_spike_detection_flags_temperature_spike_against_stable_history():
    stage = SpikeDetectionStage()
    history = [
        _frame(sequence_id=i, tyre_temperature=TyreTemperatures(front_left_c=90, front_right_c=90, rear_left_c=92, rear_right_c=92))
        for i in range(10)
    ]
    spiked = _frame(
        sequence_id=10,
        tyre_temperature=TyreTemperatures(front_left_c=190, front_right_c=190, rear_left_c=190, rear_right_c=190),
    )
    log = _log()

    result = stage.process(spiked, _ctx(recent_frames=history), log)

    assert result.tyre_temperature.front_left_c < 190
    assert any("SPIKE" in f for f in result.data_quality_flags)


def test_spike_detection_does_not_flag_stable_readings():
    stage = SpikeDetectionStage()
    history = [_frame(sequence_id=i, speed_kph=250 + (i % 3)) for i in range(10)]
    normal = _frame(sequence_id=10, speed_kph=251.0)
    log = _log()

    result = stage.process(normal, _ctx(recent_frames=history), log)

    assert result.speed_kph == 251.0
    assert log.changes == []


def test_spike_detection_skips_when_insufficient_history():
    stage = SpikeDetectionStage()
    frame = _frame(speed_kph=900.0)  # would be a spike, but no history yet
    log = _log()

    result = stage.process(frame, _ctx(recent_frames=[]), log)

    assert result.speed_kph == 900.0  # untouched -- ImpossibleValueDetectionStage's job, not this one's


# --- SmoothingStage (noisy steering/braking) ----------------------------------


def test_smoothing_reduces_but_does_not_eliminate_a_single_noisy_reading():
    stage = SmoothingStage()
    prev = _frame(steering_angle_deg=0.0, brake_pct=0.0, throttle_pct=0.0, speed_kph=200.0)
    noisy = _frame(steering_angle_deg=20.0, brake_pct=0.0, throttle_pct=0.0, speed_kph=200.0)
    log = _log()

    result = stage.process(noisy, _ctx(previous_frame=prev), log)

    assert 0.0 < result.steering_angle_deg < 20.0
    assert len(log.changes) >= 1


def test_smoothing_noop_on_first_frame():
    stage = SmoothingStage()
    frame = _frame(steering_angle_deg=20.0)
    log = _log()

    result = stage.process(frame, _ctx(), log)
    assert result.steering_angle_deg == 20.0


# --- FeatureExtractionStage ---------------------------------------------------


def test_feature_extraction_computes_speed_delta():
    stage = FeatureExtractionStage()
    prev = _frame(speed_kph=200.0, source_timestamp=BASE_TS)
    now = _frame(speed_kph=210.0, source_timestamp=BASE_TS + timedelta(seconds=0.2))
    log = _log()

    result = stage.process(now, _ctx(previous_frame=prev), log)

    assert result.model_extra["feature_speed_delta_kph"] == pytest.approx(10.0)
    assert "feature_accel_estimate_ms2" in result.model_extra


# --- SensorConfidenceScoringStage ---------------------------------------------


def test_confidence_scoring_penalizes_recorded_issues():
    stage = SensorConfidenceScoringStage()
    frame = _frame()
    log = _log()
    log.record_issue("some_stage", NormalizationIssueSeverity.ERROR, "synthetic error")

    result = stage.process(frame, _ctx(), log)

    assert result.sensor_confidence.overall < 1.0


def test_confidence_scoring_full_confidence_with_no_issues():
    stage = SensorConfidenceScoringStage()
    frame = _frame()
    result = stage.process(frame, _ctx(), _log())
    assert result.sensor_confidence.overall == 1.0


# --- End-to-end: default_pipeline() against severe simulator noise ----------


@pytest.mark.asyncio
async def test_default_pipeline_handles_severe_noise_without_crashing():
    """Routes through SimulatorAdapter (not the bare generator) so
    transport-level corruption (drop/delay/duplicate) is actually present --
    that's applied at the adapter layer, not by TelemetryGenerator itself
    (see simulator/generator/core.py's module docstring)."""

    from backend.adapters.simulator_adapter import SimulatorAdapter

    config = GeneratorConfig(laps=1, noise=NoiseConfig.severe())
    adapter = SimulatorAdapter(config, seed=123)
    await adapter.connect()
    frames = [f async for f in adapter.stream()]
    assert len(frames) > 50

    pipeline = default_pipeline()
    results = [pipeline.process(f) for f in frames]

    surviving = [r.normalized_frame for r in results if not r.dropped]
    assert len(surviving) > 0

    # No NaNs anywhere in the output.
    for frame in surviving:
        assert frame.speed_kph is None or not math.isnan(frame.speed_kph)

    # Timestamps strictly increase across everything that survived.
    timestamps = [f.source_timestamp for f in surviving]
    assert all(timestamps[i] < timestamps[i + 1] for i in range(len(timestamps) - 1))

    # Hard physical bounds respected everywhere.
    for frame in surviving:
        if frame.speed_kph is not None:
            assert 0.0 <= frame.speed_kph <= 400.0
        if frame.tyre_age_laps is not None:
            assert frame.tyre_age_laps >= 0

    # Every surviving frame has a confidence score attached.
    assert all(f.sensor_confidence is not None for f in surviving)

    # At least some duplicates were actually dropped (severe config injects them).
    assert any(r.dropped_at_stage == "duplicate_detection" for r in results)

    # At least some issues were recorded across the whole run (proves the
    # pipeline is actually doing something, not just passing frames through).
    total_issues = sum(len(r.issues) for r in results)
    assert total_issues > 0


def test_default_pipeline_is_deterministic_given_same_input_sequence():
    config = GeneratorConfig(laps=1, noise=NoiseConfig.moderate())
    frames = list(TelemetryGenerator(config, seed=55).frames())

    results_a = [f.normalized_frame for f in (default_pipeline().process(fr) for fr in frames)]
    results_b = [f.normalized_frame for f in (default_pipeline().process(fr) for fr in frames)]

    assert [f.speed_kph if f else None for f in results_a] == [f.speed_kph if f else None for f in results_b]
