"""Concrete normalization stages (Phase 3).

Ten single-purpose stages, run in the order documented in
docs/ARCHITECTURE.md and assembled by `default_pipeline()` below. Each
stage follows the contract in `backend/normalization/base.py`: record a
`FieldChange` for anything it actually alters, an `NormalizationIssue` for
anything it notices, and never alter a value silently.

Design note on "impossible" vs "spike": an impossible value violates a hard
physical bound regardless of history (negative tyre age, a 900 kph car);
a spike is statistically anomalous relative to this car's own recent
history even though it might be within hard bounds. They're deliberately
two different stages (`ImpossibleValueDetectionStage`,
`SpikeDetectionStage`) because they need different logic: hard bounds need
no history, statistical anomalies need a rolling window.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Optional

from backend.normalization.base import (
    NormalizationContext,
    NormalizationIssueSeverity,
    NormalizationPipeline,
    NormalizationRunLog,
    NormalizationStage,
)
from backend.telemetry.schema import RaceTelemetry, SensorConfidence

# --- 1. Schema / NaN validation ---------------------------------------------

_NUMERIC_FIELDS_TO_CHECK_FOR_NAN = (
    "speed_kph",
    "acceleration_ms2",
    "longitudinal_acceleration_g",
    "lateral_acceleration_g",
    "throttle_pct",
    "brake_pct",
    "steering_angle_deg",
    "rpm",
    "fuel_load_kg",
    "gap_ahead_s",
    "gap_behind_s",
    "track_temperature_c",
    "air_temperature_c",
    "humidity_pct",
    "rain_probability",
)


class SchemaValidationStage(NormalizationStage):
    """Catches what pydantic's type system alone does not: NaN/Inf floats.

    Pydantic's `float` accepts `nan`/`inf` as structurally valid, but
    they're not usable by any downstream model. Treated as missing (set to
    `None`) so `MissingDataHandlingStage` deals with them uniformly.
    """

    name = "schema_validation"

    def process(self, frame, context, log):
        updates: dict = {}
        for field_name in _NUMERIC_FIELDS_TO_CHECK_FOR_NAN:
            value = getattr(frame, field_name)
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                updates[field_name] = None
                log.record_change(self.name, field_name, value, None, "NaN/Inf is not a usable value; treated as missing")
                log.record_issue(self.name, NormalizationIssueSeverity.ERROR, f"{field_name} was NaN/Inf", field_name)
        if not updates:
            return frame
        return frame.model_copy(update=updates)


# --- 2. Unit normalization ---------------------------------------------------


class UnitNormalizationStage(NormalizationStage):
    """Folds known alternate-unit fields (arriving via schema extras) into
    the canonical field.

    The common schema bakes units into field names (`speed_kph`, not
    `speed`), so a compliant adapter needs no conversion. This stage exists
    for the case a source hands off a value in a different unit under a
    differently-named extra field (e.g. a hypothetical vendor feed sending
    `speed_ms`) -- illustrated with two conversions; extend this table if a
    real adapter needs more.
    """

    name = "unit_normalization"

    def process(self, frame, context, log):
        updates: dict = {}
        extra = frame.model_extra or {}

        if frame.speed_kph is None and "speed_ms" in extra:
            converted = extra["speed_ms"] * 3.6
            updates["speed_kph"] = converted
            log.record_change(self.name, "speed_kph", None, converted, "converted from extra field speed_ms (m/s -> kph)")

        if frame.fuel_load_kg is None and "fuel_load_lb" in extra:
            converted = extra["fuel_load_lb"] * 0.453592
            updates["fuel_load_kg"] = converted
            log.record_change(self.name, "fuel_load_kg", None, converted, "converted from extra field fuel_load_lb (lb -> kg)")

        if not updates:
            return frame
        return frame.model_copy(update=updates)


# --- 3. Timestamp alignment ---------------------------------------------------


class TimestampAlignmentStage(NormalizationStage):
    """Enforces monotonically increasing `source_timestamp` per car.

    Real/simulated jitter can make consecutive timestamps arrive
    non-monotonic. Rather than reorder (impossible in a streaming,
    one-frame-at-a-time pipeline), this nudges a non-monotonic timestamp
    forward to just after the previous frame's, preserving arrival order
    while recording exactly what correction was made.
    """

    name = "timestamp_alignment"
    MIN_STEP = timedelta(milliseconds=1)

    def process(self, frame, context, log):
        prev = context.previous_frame
        if prev is None or frame.source_timestamp > prev.source_timestamp:
            return frame

        corrected = prev.source_timestamp + self.MIN_STEP
        log.record_change(
            self.name, "source_timestamp", frame.source_timestamp, corrected, "non-monotonic timestamp corrected forward"
        )
        log.record_issue(self.name, NormalizationIssueSeverity.WARNING, "source_timestamp was not monotonically increasing")
        return frame.model_copy(update={"source_timestamp": corrected})


# --- 4. Duplicate detection ---------------------------------------------------


class DuplicateDetectionStage(NormalizationStage):
    """Drops an exact repeat of the previous frame.

    Primary key is `sequence_id` when the adapter provides one (every
    adapter in this project does). Falls back to comparing content fields
    (excluding envelope/provenance fields that legitimately differ, like
    `ingest_timestamp`) when `sequence_id` is absent.
    """

    name = "duplicate_detection"
    _ENVELOPE_FIELDS = {"ingest_timestamp", "sequence_id", "sensor_confidence", "data_quality_flags"}

    def process(self, frame, context, log):
        prev = context.previous_frame
        if prev is None:
            return frame

        if frame.sequence_id is not None and prev.sequence_id is not None:
            is_duplicate = frame.sequence_id == prev.sequence_id
        else:
            is_duplicate = frame.model_dump(exclude=self._ENVELOPE_FIELDS) == prev.model_dump(
                exclude=self._ENVELOPE_FIELDS
            )

        if is_duplicate:
            log.record_issue(self.name, NormalizationIssueSeverity.INFO, "duplicate frame dropped")
            return None
        return frame


# --- 5. Missing-data handling (last-observation-carried-forward) -----------


_LOCF_FIELDS = ("speed_kph", "throttle_pct", "brake_pct", "steering_angle_deg", "fuel_load_kg")


class MissingDataHandlingStage(NormalizationStage):
    """Fills missing values via last-observation-carried-forward (LOCF).

    True interpolation needs a known point on both sides; a streaming,
    one-frame-at-a-time pipeline only has the past, so LOCF is the standard
    online approximation. Every filled field is tagged in
    `data_quality_flags` so downstream consumers can see it was not an
    original reading.
    """

    name = "missing_data_handling"

    def process(self, frame, context, log):
        prev = context.previous_frame
        updates: dict = {}
        flags = list(frame.data_quality_flags)

        for field_name in _LOCF_FIELDS:
            if getattr(frame, field_name) is not None:
                continue
            if prev is None or getattr(prev, field_name) is None:
                log.record_issue(
                    self.name,
                    NormalizationIssueSeverity.WARNING,
                    f"{field_name} missing with no prior value to carry forward",
                    field_name,
                )
                continue
            carried = getattr(prev, field_name)
            updates[field_name] = carried
            flags.append(f"INTERPOLATED:{field_name}")
            log.record_change(self.name, field_name, None, carried, "last-observation-carried-forward")

        if not updates:
            return frame
        updates["data_quality_flags"] = flags
        return frame.model_copy(update=updates)


# --- 6. Impossible-value detection (hard physical bounds) ------------------


@dataclass(frozen=True)
class _Bound:
    field: str
    lo: Optional[float]
    hi: Optional[float]


_HARD_BOUNDS = (
    _Bound("speed_kph", 0.0, 400.0),
    _Bound("throttle_pct", 0.0, 100.0),
    _Bound("brake_pct", 0.0, 100.0),
    _Bound("rain_probability", 0.0, 1.0),
    _Bound("humidity_pct", 0.0, 100.0),
    _Bound("fuel_load_kg", 0.0, 200.0),
    _Bound("tyre_age_laps", 0, None),
)


class ImpossibleValueDetectionStage(NormalizationStage):
    """Clamps values that violate a hard physical bound, regardless of history.

    Bounds are intentionally generous (e.g. 400 kph, not a real car's true
    top speed) -- the goal is catching genuinely impossible telemetry
    (negative tyre age, a sensor glitch reporting 900 kph), not
    second-guessing legitimate extremes. Statistically-anomalous-but-
    in-bounds values are `SpikeDetectionStage`'s job, not this one's.
    """

    name = "impossible_value_detection"

    def process(self, frame, context, log):
        updates: dict = {}
        flags = list(frame.data_quality_flags)

        for bound in _HARD_BOUNDS:
            value = getattr(frame, bound.field)
            if value is None:
                continue
            clamped = value
            if bound.lo is not None and value < bound.lo:
                clamped = bound.lo
            elif bound.hi is not None and value > bound.hi:
                clamped = bound.hi
            if clamped != value:
                updates[bound.field] = clamped
                flags.append(f"IMPOSSIBLE_VALUE:{bound.field}")
                log.record_change(self.name, bound.field, value, clamped, f"clamped to physical bound [{bound.lo}, {bound.hi}]")
                log.record_issue(
                    self.name, NormalizationIssueSeverity.ERROR, f"{bound.field}={value} outside physical bounds", bound.field
                )

        if not updates:
            return frame
        updates["data_quality_flags"] = flags
        return frame.model_copy(update=updates)


# --- 7. Spike / outlier detection (statistical, history-based) -------------


def _rolling_mean_std(values: list[float]) -> Optional[tuple[float, float]]:
    if len(values) < 5:
        return None
    return statistics.fmean(values), statistics.pstdev(values)


@dataclass(frozen=True)
class _SpikeChannel:
    field: str
    accessor: Callable[[RaceTelemetry], Optional[float]]
    z_threshold: float
    min_std_floor: float
    min_abs_delta: float


def _tyre_temp_avg(frame: RaceTelemetry) -> Optional[float]:
    tt = frame.tyre_temperature
    values = [v for v in (tt.front_left_c, tt.front_right_c, tt.rear_left_c, tt.rear_right_c) if v is not None]
    return statistics.fmean(values) if values else None


_SPIKE_CHANNELS = (
    _SpikeChannel("speed_kph", lambda f: f.speed_kph, z_threshold=5.0, min_std_floor=2.0, min_abs_delta=40.0),
    _SpikeChannel("tyre_temperature_avg_c", _tyre_temp_avg, z_threshold=3.5, min_std_floor=1.0, min_abs_delta=8.0),
)


class SpikeDetectionStage(NormalizationStage):
    """Flags/clamps values that are statistically anomalous vs. this car's
    own recent history (rolling z-score), even when within hard bounds.

    Known limitation (documented, not hidden): a fixed z-score threshold
    will occasionally mistake a legitimate hard-braking event for a speed
    spike, and can miss a spike that lands inside an already-noisy window's
    inflated variance. A production version would condition the expected
    value on track position; this pipeline has no track-geometry awareness
    by design (see docs/ARCHITECTURE.md on simulator independence), so it
    uses a purely statistical, history-based estimate instead. Given that
    tradeoff, thresholds are set conservatively (wide) to favor precision
    over recall.
    """

    name = "spike_detection"

    def process(self, frame, context, log):
        updates: dict = {}
        flags = list(frame.data_quality_flags)

        for channel in _SPIKE_CHANNELS:
            current = channel.accessor(frame)
            if current is None:
                continue
            history = [v for f in context.recent_frames for v in [channel.accessor(f)] if v is not None]
            stats = _rolling_mean_std(history[-20:])
            if stats is None:
                continue
            mean, std = stats
            effective_std = max(std, channel.min_std_floor)
            delta = abs(current - mean)
            if delta > channel.z_threshold * effective_std and delta > channel.min_abs_delta:
                clamped = mean
                flags.append(f"SPIKE:{channel.field}")
                log.record_issue(
                    self.name,
                    NormalizationIssueSeverity.WARNING,
                    f"{channel.field}={current:.1f} is a statistical outlier (rolling mean={mean:.1f}, std={std:.1f})",
                    channel.field,
                )
                if channel.field == "speed_kph":
                    updates["speed_kph"] = clamped
                    log.record_change(self.name, "speed_kph", current, clamped, "clamped to rolling mean (spike)")
                elif channel.field == "tyre_temperature_avg_c":
                    tt = frame.tyre_temperature
                    scale = clamped / current if current else 1.0
                    new_tt = tt.model_copy(
                        update={
                            k: (v * scale if v is not None else None)
                            for k, v in tt.model_dump().items()
                        }
                    )
                    updates["tyre_temperature"] = new_tt
                    log.record_change(self.name, "tyre_temperature", current, clamped, "scaled toward rolling mean (spike)")

        if not updates:
            return frame
        updates["data_quality_flags"] = flags
        return frame.model_copy(update=updates)


# --- 8. Smoothing (exponential moving average) ------------------------------


_EMA_FIELDS = {"speed_kph": 0.4, "steering_angle_deg": 0.35, "brake_pct": 0.5, "throttle_pct": 0.5}


class SmoothingStage(NormalizationStage):
    """Exponential moving average on a few noisy channels.

    Runs after impossible-value and spike correction so it's smoothing
    residual sensor jitter, not large corrupted excursions. Each field's
    alpha trades responsiveness for noise reduction; see `_EMA_FIELDS`.
    """

    name = "smoothing"

    def process(self, frame, context, log):
        prev = context.previous_frame
        if prev is None:
            return frame

        updates: dict = {}
        for field_name, alpha in _EMA_FIELDS.items():
            current = getattr(frame, field_name)
            previous_smoothed = getattr(prev, field_name)
            if current is None or previous_smoothed is None:
                continue
            smoothed = alpha * current + (1 - alpha) * previous_smoothed
            if smoothed != current:
                updates[field_name] = smoothed
                log.record_change(self.name, field_name, current, smoothed, f"EMA(alpha={alpha})")

        if not updates:
            return frame
        return frame.model_copy(update=updates)


# --- 9. Feature extraction ---------------------------------------------------


class FeatureExtractionStage(NormalizationStage):
    """Attaches a small set of cross-frame derived features under `extra`.

    These are computed conveniences for downstream models (Phase 5/6), not
    raw telemetry -- kept in `model_extra` (see the schema's
    `extra="allow"`) rather than as first-class fields so it stays obvious
    they're derived. See docs/DATA_MODEL.md.
    """

    name = "feature_extraction"

    def process(self, frame, context, log):
        prev = context.previous_frame
        features: dict = {}

        if prev is not None and frame.speed_kph is not None and prev.speed_kph is not None:
            dt = (frame.source_timestamp - prev.source_timestamp).total_seconds()
            if dt > 0:
                features["feature_speed_delta_kph"] = frame.speed_kph - prev.speed_kph
                features["feature_accel_estimate_ms2"] = ((frame.speed_kph - prev.speed_kph) / 3.6) / dt

        if not features:
            return frame
        return frame.model_copy(update=features)


# --- 10. Sensor-confidence scoring ------------------------------------------


class SensorConfidenceScoringStage(NormalizationStage):
    """Aggregates everything recorded so far in this run's log into a
    `SensorConfidence` score.

    Because `log` is the same `NormalizationRunLog` instance threaded
    through the whole pipeline call, every earlier stage's issues/changes
    for THIS frame are visible here -- confidence is a genuine summary of
    what happened to this frame, not an independent guess.
    """

    name = "sensor_confidence_scoring"
    _ERROR_PENALTY = 0.15
    _WARNING_PENALTY = 0.05

    def process(self, frame, context, log):
        error_count = sum(1 for i in log.issues if i.severity == NormalizationIssueSeverity.ERROR)
        warning_count = sum(1 for i in log.issues if i.severity == NormalizationIssueSeverity.WARNING)
        overall = max(0.0, 1.0 - error_count * self._ERROR_PENALTY - warning_count * self._WARNING_PENALTY)

        def field_confidence(*field_names: str) -> float:
            touched = any(c.field in field_names for c in log.changes)
            return 0.6 if touched else 1.0

        confidence = SensorConfidence(
            overall=overall,
            speed=field_confidence("speed_kph"),
            tyre_temperature=field_confidence("tyre_temperature", "tyre_temperature_avg_c"),
            position=field_confidence("position"),
        )
        return frame.model_copy(update={"sensor_confidence": confidence})


# --- Pipeline assembly --------------------------------------------------------


def default_pipeline() -> NormalizationPipeline:
    """The full 10-stage pipeline, in the order documented in docs/ARCHITECTURE.md."""

    return NormalizationPipeline(
        [
            SchemaValidationStage(),
            UnitNormalizationStage(),
            TimestampAlignmentStage(),
            DuplicateDetectionStage(),
            MissingDataHandlingStage(),
            ImpossibleValueDetectionStage(),
            SpikeDetectionStage(),
            SmoothingStage(),
            FeatureExtractionStage(),
            SensorConfidenceScoringStage(),
        ]
    )
