"""The event vocabulary and `RaceEvent` record.

All fifteen event types from the problem statement are declared in
`EventType` so the vocabulary is complete and stable from the start, but
not all are detectable yet -- each requires whatever intelligence layer
produces its evidence. `DETECTOR_STATUS` below states plainly which are
live today and which are waiting on a later phase; this file must be kept
in sync with reality (never claim a detector exists that doesn't).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    TYRE_CLIFF_APPROACHING = "TYRE_CLIFF_APPROACHING"
    TYRE_DEGRADATION_ACCELERATING = "TYRE_DEGRADATION_ACCELERATING"
    OPPONENT_PITTING = "OPPONENT_PITTING"
    UNDERCUT_OPPORTUNITY = "UNDERCUT_OPPORTUNITY"
    OVERCUT_OPPORTUNITY = "OVERCUT_OPPORTUNITY"
    FREE_PIT_WINDOW = "FREE_PIT_WINDOW"
    SAFETY_CAR = "SAFETY_CAR"
    VSC = "VSC"
    RAIN_INCOMING = "RAIN_INCOMING"
    TRAFFIC_RELEASE = "TRAFFIC_RELEASE"
    POSITION_THREAT = "POSITION_THREAT"
    POSITION_OPPORTUNITY = "POSITION_OPPORTUNITY"
    PACE_DROP = "PACE_DROP"
    RACING_LINE_DEGRADATION = "RACING_LINE_DEGRADATION"
    STRATEGY_FAILURE = "STRATEGY_FAILURE"


# Kept in sync by hand, checked by tests/test_events.py::test_detector_status_matches_reality.
DETECTOR_STATUS: dict[EventType, str] = {
    EventType.SAFETY_CAR: "live (Phase 8, from RaceTelemetry.safety_car)",
    EventType.VSC: "live (Phase 8, from RaceTelemetry.vsc)",
    EventType.TYRE_CLIFF_APPROACHING: "live (Phase 8, from backend/tyre's cliff_probability)",
    EventType.TYRE_DEGRADATION_ACCELERATING: "live (Phase 8, from backend/tyre's degradation_acceleration)",
    EventType.PACE_DROP: "live (Phase 8, from backend/pace's pace_delta)",
    EventType.FREE_PIT_WINDOW: "live (Phase 8, from backend/state's baseline recommended_pit_window)",
    EventType.RAIN_INCOMING: "not yet detectable -- needs Phase 13 (weather intelligence)",
    EventType.OPPONENT_PITTING: "not yet detectable -- needs Phase 14 (opponent intelligence)",
    EventType.UNDERCUT_OPPORTUNITY: "not yet detectable -- needs Phase 14 (opponent intelligence)",
    EventType.OVERCUT_OPPORTUNITY: "not yet detectable -- needs Phase 14 (opponent intelligence)",
    EventType.TRAFFIC_RELEASE: "not yet detectable -- needs Phase 14 (opponent intelligence)",
    EventType.POSITION_THREAT: "not yet detectable -- needs Phase 14 (opponent intelligence)",
    EventType.POSITION_OPPORTUNITY: "not yet detectable -- needs Phase 14 (opponent intelligence)",
    EventType.RACING_LINE_DEGRADATION: "not yet detectable -- needs Phase 15 (racing-line intelligence)",
    EventType.STRATEGY_FAILURE: "not yet detectable -- needs Phase 9 (strategy engine) to have a decision to evaluate",
}


class EventSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class RaceEvent:
    event_type: EventType
    car_id: str
    lap: int
    timestamp: datetime
    severity: EventSeverity
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    affected_systems: tuple[str, ...] = ()
    message: str = ""
