"""Normalization pipeline interfaces.

Telemetry arriving from any adapter is assumed imperfect: missing fields,
duplicate frames, out-of-order or jittered timestamps, sensor spikes,
physically impossible values, dropped packets. The normalization pipeline
is an ordered sequence of single-purpose stages that each address one
concern -- schema validation, unit normalization, timestamp alignment,
duplicate detection, missing-value handling, impossible-value detection,
spike detection, smoothing, feature extraction, and sensor-confidence
scoring (see docs/ARCHITECTURE.md).

Concrete stage implementations land in Phase 3. This module defines the
contract, split into two deliberately separate kinds of state:

  * `NormalizationContext` -- rolling, cross-frame memory a stage needs
    (previous frame, bounded recent history). Scoped per car, lives for the
    life of the pipeline.
  * `NormalizationRunLog` -- everything a stage records about *this one
    frame* (issues found, fields changed and why). Scoped per call to
    `pipeline.process()`, discarded (well, returned) after.

Keeping those separate is what makes "never silently modify telemetry
without recording what changed and why" (engineering rule 19) and full
telemetry provenance (raw value + normalized value + confidence + issues,
per frame) actually hold: a `NormalizationResult` below carries the raw
frame, the normalized frame, and exactly what changed between them, for
every single frame that passes through -- not an ever-growing, frame-
unattributed log on the context.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.telemetry.schema import RaceTelemetry


class NormalizationIssueSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class NormalizationIssue:
    """One thing a stage noticed about a frame."""

    stage: str
    severity: NormalizationIssueSeverity
    message: str
    field: Optional[str] = None


@dataclass(frozen=True)
class FieldChange:
    """One field a stage actually modified, and why.

    `before`/`after` are the raw Python values (not full frames) so a UI or
    log can show e.g. `speed_kph: 312.0 -> 231.4 (spike clamped to 3-sigma)`
    without diffing two whole `RaceTelemetry` objects.
    """

    stage: str
    field: str
    before: Any
    after: Any
    reason: str


@dataclass
class NormalizationRunLog:
    """Everything recorded about one frame's pass through the pipeline."""

    issues: list[NormalizationIssue] = field(default_factory=list)
    changes: list[FieldChange] = field(default_factory=list)

    def record_issue(
        self,
        stage: str,
        severity: NormalizationIssueSeverity,
        message: str,
        field_name: Optional[str] = None,
    ) -> None:
        self.issues.append(
            NormalizationIssue(stage=stage, severity=severity, message=message, field=field_name)
        )

    def record_change(self, stage: str, field_name: str, before: Any, after: Any, reason: str) -> None:
        self.changes.append(
            FieldChange(stage=stage, field=field_name, before=before, after=after, reason=reason)
        )


@dataclass
class NormalizationContext:
    """Rolling per-car memory a stage may need across frames.

    Cross-frame state only (previous frame, bounded history) -- per-frame
    observability lives in `NormalizationRunLog`, not here. Keeping state
    stateless-per-stage and reproducible from `(frames, initial context)` is
    what deterministic replay (backend/adapters/replay.py) depends on.
    """

    car_id: str
    previous_frame: Optional[RaceTelemetry] = None
    recent_frames: list[RaceTelemetry] = field(default_factory=list)
    max_history: int = 50


@dataclass
class NormalizationResult:
    """Full provenance for one frame's trip through the pipeline."""

    raw_frame: RaceTelemetry
    normalized_frame: Optional[RaceTelemetry]
    issues: list[NormalizationIssue]
    changes: list[FieldChange]
    dropped_at_stage: Optional[str] = None

    @property
    def dropped(self) -> bool:
        return self.normalized_frame is None


class NormalizationStage(abc.ABC):
    """One concern in the normalization pipeline.

    A stage receives the frame produced by the previous stage, rolling
    per-car context, and a run log to record into. It returns the
    (possibly modified) frame, or `None` to drop it entirely -- later
    stages are then skipped for that frame. A stage that changes a field
    must call `log.record_change(...)`; a stage that notices but does not
    change something must call `log.record_issue(...)`. Silently altering a
    value with neither is a bug, not a shortcut.
    """

    name: str

    @abc.abstractmethod
    def process(
        self,
        frame: RaceTelemetry,
        context: NormalizationContext,
        log: NormalizationRunLog,
    ) -> Optional[RaceTelemetry]:
        """Apply this stage's logic; return the resulting frame or None to drop it."""


class NormalizationPipeline:
    """Runs an ordered list of stages over each incoming frame, per car."""

    def __init__(self, stages: list[NormalizationStage]):
        self._stages = stages
        self._contexts: dict[str, NormalizationContext] = {}

    def get_context(self, car_id: str) -> Optional[NormalizationContext]:
        return self._contexts.get(car_id)

    def process(self, frame: RaceTelemetry) -> NormalizationResult:
        context = self._contexts.setdefault(frame.car_id, NormalizationContext(car_id=frame.car_id))
        log = NormalizationRunLog()

        current: Optional[RaceTelemetry] = frame
        dropped_at_stage: Optional[str] = None
        for stage in self._stages:
            result = stage.process(current, context, log)
            if result is None:
                dropped_at_stage = stage.name
                current = None
                break
            current = result

        if current is not None:
            context.previous_frame = current
            context.recent_frames.append(current)
            if len(context.recent_frames) > context.max_history:
                context.recent_frames = context.recent_frames[-context.max_history :]

        return NormalizationResult(
            raw_frame=frame,
            normalized_frame=current,
            issues=log.issues,
            changes=log.changes,
            dropped_at_stage=dropped_at_stage,
        )
