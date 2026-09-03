"""`EventDetectionEngine`: watches `RaceState` for transitions worth reacting to.

Called after every frame (cheap: a handful of comparisons against the
previous call's remembered values), but events only fire on genuine
transitions, not on every call -- edge-triggering against remembered state
is what makes that correct without needing separate per-lap bookkeeping:
every field this engine watches (tyre cliff probability, degradation
acceleration, pace delta, the pit window) is itself only updated at lap
boundaries by the upstream Phase 5/6/7 estimators, so within a lap the
"current vs. previous" comparison naturally sees no change and stays
silent. SC/VSC are watched on the raw per-frame flag, so those fire the
instant the flag flips, not just at the next lap boundary -- correctly,
since a safety car deployment shouldn't wait for a lap to complete before
the pit wall hears about it.

This does not "recompute an enormous simulation" per packet -- it's a
constant amount of comparison work per frame, per the Phase 8 requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from backend.events.model import EventSeverity, EventType, RaceEvent
from backend.observability.logging import get_logger
from backend.state.race_state import RaceState
from backend.weather.model import WeatherAssessment

log = get_logger("events.detector")


@dataclass
class DetectionThresholds:
    tyre_cliff_probability: float = 0.4
    degradation_acceleration_s_per_lap2: float = 0.02
    pace_drop_s: float = 0.5


@dataclass
class _CarMemory:
    safety_car: bool = False
    vsc: bool = False
    cliff_probability_above_threshold: bool = False
    degradation_accelerating: bool = False
    pace_drop_active: bool = False
    in_pit_window: bool = False
    rain_incoming_active: bool = False


class EventDetectionEngine:
    def __init__(self, thresholds: DetectionThresholds | None = None, history_size: int = 200):
        self._thresholds = thresholds or DetectionThresholds()
        self._memory: dict[str, _CarMemory] = {}
        self._history: dict[str, list[RaceEvent]] = {}
        self._history_size = history_size

    def recent_events(self, car_id: str) -> list[RaceEvent]:
        return list(self._history.get(car_id, []))

    def detect(self, state: RaceState, weather_assessment: Optional[WeatherAssessment] = None) -> list[RaceEvent]:
        mem = self._memory.setdefault(state.car_id, _CarMemory())
        events: list[RaceEvent] = []
        now = state.last_updated or datetime.now(timezone.utc)

        events += self._detect_flag_events(state, mem, now)
        events += self._detect_tyre_events(state, mem, now)
        events += self._detect_pace_events(state, mem, now)
        events += self._detect_pit_window_events(state, mem, now)
        events += self._detect_weather_events(state, mem, now, weather_assessment)

        if events:
            bucket = self._history.setdefault(state.car_id, [])
            bucket.extend(events)
            if len(bucket) > self._history_size:
                del bucket[: len(bucket) - self._history_size]
            for event in events:
                log.info(
                    "race event detected",
                    extra={
                        "fields": {
                            "event_type": event.event_type.value,
                            "car_id": event.car_id,
                            "lap": event.lap,
                            "severity": event.severity.value,
                            "confidence": event.confidence,
                        }
                    },
                )

        return events

    def _detect_flag_events(self, state: RaceState, mem: _CarMemory, now: datetime) -> list[RaceEvent]:
        events = []
        if state.safety_car and not mem.safety_car:
            events.append(
                RaceEvent(
                    event_type=EventType.SAFETY_CAR,
                    car_id=state.car_id,
                    lap=state.current_lap,
                    timestamp=now,
                    severity=EventSeverity.CRITICAL,
                    confidence=1.0,
                    evidence={"safety_car": True},
                    affected_systems=("strategy", "pit_wall", "hq"),
                    message="Safety car deployed.",
                )
            )
        if state.vsc and not mem.vsc:
            events.append(
                RaceEvent(
                    event_type=EventType.VSC,
                    car_id=state.car_id,
                    lap=state.current_lap,
                    timestamp=now,
                    severity=EventSeverity.WARNING,
                    confidence=1.0,
                    evidence={"vsc": True},
                    affected_systems=("strategy", "pit_wall", "hq"),
                    message="Virtual safety car deployed.",
                )
            )
        mem.safety_car = state.safety_car
        mem.vsc = state.vsc
        return events

    def _detect_tyre_events(self, state: RaceState, mem: _CarMemory, now: datetime) -> list[RaceEvent]:
        events = []
        threshold = self._thresholds

        cliff_prob = state.tyre_cliff_probability
        above = cliff_prob is not None and cliff_prob >= threshold.tyre_cliff_probability
        if above and not mem.cliff_probability_above_threshold:
            events.append(
                RaceEvent(
                    event_type=EventType.TYRE_CLIFF_APPROACHING,
                    car_id=state.car_id,
                    lap=state.current_lap,
                    timestamp=now,
                    severity=EventSeverity.WARNING,
                    confidence=cliff_prob,
                    evidence={"tyre_cliff_probability": cliff_prob, "tyre_age_laps": state.tyre_age_laps},
                    affected_systems=("strategy", "pit_wall"),
                    message=f"Tyre cliff probability at {cliff_prob:.0%}.",
                )
            )
        mem.cliff_probability_above_threshold = above

        accel = state.degradation_acceleration_s_per_lap2
        accelerating = accel is not None and accel >= threshold.degradation_acceleration_s_per_lap2
        if accelerating and not mem.degradation_accelerating:
            events.append(
                RaceEvent(
                    event_type=EventType.TYRE_DEGRADATION_ACCELERATING,
                    car_id=state.car_id,
                    lap=state.current_lap,
                    timestamp=now,
                    severity=EventSeverity.WARNING,
                    confidence=0.7,
                    evidence={"degradation_acceleration_s_per_lap2": accel},
                    affected_systems=("strategy", "pit_wall"),
                    message="Tyre degradation rate is accelerating.",
                )
            )
        mem.degradation_accelerating = accelerating
        return events

    def _detect_pace_events(self, state: RaceState, mem: _CarMemory, now: datetime) -> list[RaceEvent]:
        events = []
        delta = state.pace_delta_s
        dropping = delta is not None and delta >= self._thresholds.pace_drop_s
        if dropping and not mem.pace_drop_active:
            events.append(
                RaceEvent(
                    event_type=EventType.PACE_DROP,
                    car_id=state.car_id,
                    lap=state.current_lap,
                    timestamp=now,
                    severity=EventSeverity.INFO if delta < 2 * self._thresholds.pace_drop_s else EventSeverity.WARNING,
                    confidence=0.6,
                    evidence={"pace_delta_s": delta, "current_pace_s": state.current_pace_s},
                    affected_systems=("strategy", "hq"),
                    message=f"Lap {state.current_lap} was {delta:.2f}s slower than expected.",
                )
            )
        mem.pace_drop_active = dropping
        return events

    def _detect_pit_window_events(self, state: RaceState, mem: _CarMemory, now: datetime) -> list[RaceEvent]:
        events = []
        window = state.baseline_trajectory.recommended_pit_window if state.baseline_trajectory else None
        in_window = window is not None and window[0] <= state.current_lap <= window[1]
        if in_window and not mem.in_pit_window:
            events.append(
                RaceEvent(
                    event_type=EventType.FREE_PIT_WINDOW,
                    car_id=state.car_id,
                    lap=state.current_lap,
                    timestamp=now,
                    severity=EventSeverity.INFO,
                    confidence=0.6,
                    evidence={"recommended_pit_window": window},
                    affected_systems=("strategy", "pit_wall"),
                    message=f"Entering tyre-life-driven pit window {window}.",
                )
            )
        mem.in_pit_window = in_window
        return events

    def _detect_weather_events(
        self, state: RaceState, mem: _CarMemory, now: datetime, weather_assessment: Optional[WeatherAssessment]
    ) -> list[RaceEvent]:
        events = []
        wetting = (
            weather_assessment is not None
            and weather_assessment.transitioning
            and weather_assessment.trend_per_lap is not None
            and weather_assessment.trend_per_lap > 0
        )
        if wetting and not mem.rain_incoming_active:
            events.append(
                RaceEvent(
                    event_type=EventType.RAIN_INCOMING,
                    car_id=state.car_id,
                    lap=state.current_lap,
                    timestamp=now,
                    severity=EventSeverity.WARNING,
                    confidence=weather_assessment.confidence,
                    evidence={
                        "rain_probability": weather_assessment.rain_probability,
                        "trend_per_lap": weather_assessment.trend_per_lap,
                    },
                    affected_systems=("strategy", "pit_wall", "hq"),
                    message=f"Rain probability rising at {weather_assessment.trend_per_lap:.2f}/lap.",
                )
            )
        mem.rain_incoming_active = wetting
        return events
