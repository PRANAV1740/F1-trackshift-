"""Tests for the normalization pipeline contract (backend/normalization/base.py).

No concrete stage exists yet (Phase 3). These tests exercise the interface
with minimal dummy stages so the contract -- and the provenance guarantee
(raw frame + normalized frame + recorded changes/issues, per frame) -- is
validated before any real stage is written against it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from backend.normalization.base import (
    NormalizationContext,
    NormalizationIssueSeverity,
    NormalizationPipeline,
    NormalizationRunLog,
    NormalizationStage,
)
from backend.telemetry.schema import RaceTelemetry


def test_normalization_stage_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        NormalizationStage()  # type: ignore[abstract]


class PassThroughStage(NormalizationStage):
    name = "pass_through"

    def process(
        self, frame: RaceTelemetry, context: NormalizationContext, log: NormalizationRunLog
    ) -> Optional[RaceTelemetry]:
        return frame


class DropDuplicateSequenceStage(NormalizationStage):
    """Illustrative duplicate-detection stage: drops a frame with a repeated sequence_id."""

    name = "drop_duplicate_sequence"

    def process(
        self, frame: RaceTelemetry, context: NormalizationContext, log: NormalizationRunLog
    ) -> Optional[RaceTelemetry]:
        if context.previous_frame is not None and frame.sequence_id == context.previous_frame.sequence_id:
            log.record_issue(self.name, NormalizationIssueSeverity.INFO, "duplicate sequence_id dropped")
            return None
        return frame


class ClampNegativeTyreAgeStage(NormalizationStage):
    """Illustrative impossible-value-detection stage: clamps (and records) bad tyre age."""

    name = "clamp_impossible_values"

    def process(
        self, frame: RaceTelemetry, context: NormalizationContext, log: NormalizationRunLog
    ) -> Optional[RaceTelemetry]:
        if frame.tyre_age_laps is not None and frame.tyre_age_laps < 0:
            before = frame.tyre_age_laps
            frame = frame.model_copy(
                update={
                    "tyre_age_laps": 0,
                    "data_quality_flags": frame.data_quality_flags + ["IMPOSSIBLE_VALUE"],
                }
            )
            log.record_change(self.name, "tyre_age_laps", before, 0, "negative tyre age clamped to 0")
            log.record_issue(
                self.name,
                NormalizationIssueSeverity.ERROR,
                "tyre_age_laps was negative",
                field_name="tyre_age_laps",
            )
        return frame


def _frame(**overrides) -> RaceTelemetry:
    defaults = dict(
        source="SIMULATOR",
        source_timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        car_id="44",
        lap=1,
    )
    defaults.update(overrides)
    return RaceTelemetry(**defaults)


def test_pipeline_runs_stages_in_order_and_updates_context():
    pipeline = NormalizationPipeline([PassThroughStage()])

    result = pipeline.process(_frame(sequence_id=1))

    assert result.normalized_frame is not None
    assert result.raw_frame is not result.normalized_frame or result.raw_frame == result.normalized_frame
    assert not result.dropped
    context = pipeline.get_context("44")
    assert context is not None
    assert context.previous_frame is result.normalized_frame
    assert context.recent_frames == [result.normalized_frame]


def test_stage_can_drop_a_frame_and_result_reports_it():
    pipeline = NormalizationPipeline([DropDuplicateSequenceStage()])

    first = pipeline.process(_frame(sequence_id=7))
    second = pipeline.process(_frame(sequence_id=7))

    assert not first.dropped
    assert second.dropped
    assert second.normalized_frame is None
    assert second.dropped_at_stage == "drop_duplicate_sequence"
    # The raw frame is always preserved even when dropped -- that's the provenance guarantee.
    assert second.raw_frame.sequence_id == 7

    context = pipeline.get_context("44")
    assert context.previous_frame is first.normalized_frame
    assert context.recent_frames == [first.normalized_frame]


def test_stage_records_change_with_before_and_after_values():
    """Demonstrates the provenance guarantee: the schema allows a negative
    tyre age to exist (see test_telemetry_schema), and a normalization
    stage is where it actually gets caught, corrected, AND recorded.
    """

    pipeline = NormalizationPipeline([ClampNegativeTyreAgeStage()])

    result = pipeline.process(_frame(tyre_age_laps=-2))

    assert result.raw_frame.tyre_age_laps == -2
    assert result.normalized_frame.tyre_age_laps == 0
    assert "IMPOSSIBLE_VALUE" in result.normalized_frame.data_quality_flags

    assert len(result.changes) == 1
    assert result.changes[0].field == "tyre_age_laps"
    assert result.changes[0].before == -2
    assert result.changes[0].after == 0

    assert len(result.issues) == 1
    assert result.issues[0].severity == NormalizationIssueSeverity.ERROR
    assert result.issues[0].field == "tyre_age_laps"


def test_pipeline_keeps_separate_context_per_car():
    pipeline = NormalizationPipeline([PassThroughStage()])

    pipeline.process(_frame(car_id="44", sequence_id=1))
    pipeline.process(_frame(car_id="1", sequence_id=1))

    assert pipeline.get_context("44") is not None
    assert pipeline.get_context("1") is not None
    assert pipeline.get_context("99") is None


def test_recent_frames_history_is_capped():
    pipeline = NormalizationPipeline([PassThroughStage()])
    for i in range(60):
        pipeline.process(_frame(sequence_id=i))

    result = pipeline.process(_frame(sequence_id=60))
    context = pipeline.get_context("44")
    assert len(context.recent_frames) == context.max_history
    assert result.normalized_frame is context.recent_frames[-1]


def test_issues_and_changes_do_not_leak_across_frames():
    """Each NormalizationResult must reflect only its own frame's pass,
    not an ever-growing log accumulated across every frame for that car.
    """

    pipeline = NormalizationPipeline([ClampNegativeTyreAgeStage()])

    first = pipeline.process(_frame(sequence_id=1, tyre_age_laps=-1))
    second = pipeline.process(_frame(sequence_id=2, tyre_age_laps=5))

    assert len(first.issues) == 1
    assert len(second.issues) == 0
    assert len(second.changes) == 0
