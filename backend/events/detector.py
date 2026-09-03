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
from backend.opponents.model import PitTimingOpportunity, classify_pit_timing_opportunity, pit_probability
from backend.state.race_state import RaceState
from backend.telemetry.schema import PitStatus
from backend.weather.model import WeatherAssessment

log = get_logger("events.detector")


@dataclass
class DetectionThresholds:
    tyre_cliff_probability: float = 0.4
    degradation_acceleration_s_per_lap2: float = 0.02
    pace_drop_s: float = 0.5
    battle_gap_s: float = 3.0  # close enough to be a live position battle
    opponent_pit_probability_committed: float = 0.6  # "about to pit" for undercut/overcut logic
    opponent_pit_probability_uncommitted: float = 0.25  # "not about to pit"
    traffic_gap_s: float = 1.5  # closer than this counts as being held up
    traffic_release_gap_s: float = 4.0  # gap must open back up past this to count as "released"
    racing_line_time_loss_s: float = 0.4  # cumulative corner time loss triggering racing line degradation


@dataclass
class _CarMemory:
    safety_car: bool = False
    vsc: bool = False
    cliff_probability_above_threshold: bool = False
    degradation_accelerating: bool = False
    pace_drop_active: bool = False
    in_pit_window: bool = False
    rain_incoming_active: bool = False
    racing_line_degradation_active: bool = False
    opponent_pit_status: dict[str, object] = field(default_factory=dict)
    undercut_opportunity_active: set = field(default_factory=set)
    overcut_opportunity_active: set = field(default_factory=set)
    position_threat_active: set = field(default_factory=set)
    position_opportunity_active: set = field(default_factory=set)
    in_traffic_of: set = field(default_factory=set)


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
        events += self._detect_racing_line_events(state, mem, now)
        events += self._detect_opponent_events(state, mem, now)

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

    def _detect_racing_line_events(self, state: RaceState, mem: _CarMemory, now: datetime) -> list[RaceEvent]:
        events = []
        analysis = state.racing_line_analysis
        degraded = analysis is not None and (
            analysis.line_degradation_detected
            or analysis.total_time_loss_s >= self._thresholds.racing_line_time_loss_s
        )
        if degraded and not mem.racing_line_degradation_active:
            events.append(
                RaceEvent(
                    event_type=EventType.RACING_LINE_DEGRADATION,
                    car_id=state.car_id,
                    lap=state.current_lap,
                    timestamp=now,
                    severity=EventSeverity.WARNING,
                    confidence=0.75,
                    evidence={
                        "total_time_loss_s": analysis.total_time_loss_s if analysis else 0.0,
                        "overall_classification": analysis.overall_classification.value if analysis else "UNKNOWN",
                    },
                    affected_systems=("strategy", "pit_wall", "hq"),
                    message=f"Racing line degradation detected (time loss {analysis.total_time_loss_s:.2f}s).",
                )
            )
        mem.racing_line_degradation_active = degraded
        return events

    def _detect_opponent_events(self, state: RaceState, mem: _CarMemory, now: datetime) -> list[RaceEvent]:
        """Uses `state.opponent_threats` (Phase 14, `backend/opponents`).

        Undercut/overcut opportunity are both about a rival AHEAD of us --
        that's who you're trying to gain track position on. They're
        differentiated by who pits first: if the rival's own pit
        probability is LOW (they're not about to react), pitting now gives
        US the jump -- an undercut opportunity. If their pit probability is
        HIGH (they're about to stop) while OUR OWN pit probability is low
        (we can afford to stay out), letting them pit first and extending
        past them is an overcut opportunity. Position threat/opportunity
        are simpler: a close rival behind is a threat to our position, a
        close rival ahead is a passing opportunity, gauged purely by gap
        (see `DetectionThresholds.battle_gap_s`).
        """

        events: list[RaceEvent] = []
        threshold = self._thresholds
        own_pit_probability = pit_probability(state)

        seen_opponents = set(state.opponent_threats.keys())

        for opponent_id, summary in state.opponent_threats.items():
            previous_status = mem.opponent_pit_status.get(opponent_id)
            if summary.pit_status == PitStatus.ENTERING_PIT and previous_status != PitStatus.ENTERING_PIT:
                events.append(
                    RaceEvent(
                        event_type=EventType.OPPONENT_PITTING,
                        car_id=state.car_id,
                        lap=state.current_lap,
                        timestamp=now,
                        severity=EventSeverity.WARNING,
                        confidence=0.9,
                        evidence={"opponent_car_id": opponent_id},
                        affected_systems=("strategy", "pit_wall"),
                        message=f"Opponent {opponent_id} is entering the pits.",
                    )
                )
            mem.opponent_pit_status[opponent_id] = summary.pit_status

            close = summary.gap_magnitude_s is not None and summary.gap_magnitude_s <= threshold.battle_gap_s

            opportunity = classify_pit_timing_opportunity(
                summary,
                own_pit_probability,
                gap_threshold_s=threshold.battle_gap_s,
                opponent_uncommitted_threshold=threshold.opponent_pit_probability_uncommitted,
                opponent_committed_threshold=threshold.opponent_pit_probability_committed,
            )
            undercut_now = opportunity == PitTimingOpportunity.UNDERCUT
            overcut_now = opportunity == PitTimingOpportunity.OVERCUT

            if undercut_now and opponent_id not in mem.undercut_opportunity_active:
                events.append(self._opponent_event(EventType.UNDERCUT_OPPORTUNITY, state, now, opponent_id, summary))
            if undercut_now:
                mem.undercut_opportunity_active.add(opponent_id)
            else:
                mem.undercut_opportunity_active.discard(opponent_id)

            if overcut_now and opponent_id not in mem.overcut_opportunity_active:
                events.append(self._opponent_event(EventType.OVERCUT_OPPORTUNITY, state, now, opponent_id, summary))
            if overcut_now:
                mem.overcut_opportunity_active.add(opponent_id)
            else:
                mem.overcut_opportunity_active.discard(opponent_id)

            if not summary.is_ahead and close:
                if opponent_id not in mem.position_threat_active:
                    events.append(self._opponent_event(EventType.POSITION_THREAT, state, now, opponent_id, summary))
                mem.position_threat_active.add(opponent_id)
            else:
                mem.position_threat_active.discard(opponent_id)

            if summary.is_ahead and close:
                if opponent_id not in mem.position_opportunity_active:
                    events.append(self._opponent_event(EventType.POSITION_OPPORTUNITY, state, now, opponent_id, summary))
                mem.position_opportunity_active.add(opponent_id)
            else:
                mem.position_opportunity_active.discard(opponent_id)

            in_traffic = summary.is_ahead and summary.gap_magnitude_s is not None and summary.gap_magnitude_s <= threshold.traffic_gap_s
            released = (
                opponent_id in mem.in_traffic_of
                and summary.gap_magnitude_s is not None
                and summary.gap_magnitude_s >= threshold.traffic_release_gap_s
            )
            if released:
                events.append(self._opponent_event(EventType.TRAFFIC_RELEASE, state, now, opponent_id, summary))
                mem.in_traffic_of.discard(opponent_id)
            elif in_traffic:
                mem.in_traffic_of.add(opponent_id)

        # Drop memory for opponents no longer tracked (e.g. lapped out of range).
        for tracked_set in (
            mem.undercut_opportunity_active,
            mem.overcut_opportunity_active,
            mem.position_threat_active,
            mem.position_opportunity_active,
            mem.in_traffic_of,
        ):
            tracked_set.intersection_update(seen_opponents)

        return events

    @staticmethod
    def _opponent_event(event_type: EventType, state: RaceState, now: datetime, opponent_id: str, summary) -> RaceEvent:
        return RaceEvent(
            event_type=event_type,
            car_id=state.car_id,
            lap=state.current_lap,
            timestamp=now,
            severity=EventSeverity.INFO,
            confidence=0.5,
            evidence={
                "opponent_car_id": opponent_id,
                "gap_magnitude_s": summary.gap_magnitude_s,
                "opponent_pit_probability": summary.pit_probability,
            },
            affected_systems=("strategy", "pit_wall"),
            message=f"{event_type.value} vs {opponent_id} (gap {summary.gap_magnitude_s}).",
        )
