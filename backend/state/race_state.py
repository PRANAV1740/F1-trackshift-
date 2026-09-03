"""The continuously-updated per-car `RaceState`.

Every intelligence module (tyre, pace, racing-line, opponents, weather,
events, strategy, prediction) reads from and writes into this one object
per car, rather than keeping its own copy of race progress -- see
docs/ARCHITECTURE.md's module-boundary rules. `RaceStateEstimator`
(estimator.py) is the only thing that constructs/mutates it from telemetry;
every later intelligence module attaches its own output to the fields
already reserved for it here (explicitly marked "populated by Phase N"
below) rather than inventing a parallel state object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from backend.opponents.model import OpponentSummary
    from backend.prediction.model import PositionPrediction
    from backend.racing_line.model import RacingLineAnalysis
    from backend.state.baseline import BaselineTrajectory
    from backend.strategy.engine import StrategyDecision
    from radio.model import DriverRadioMessage

from backend.telemetry.schema import (
    OpponentState,
    PitStatus,
    PitStop,
    RaceTelemetry,
    TrackState,
    TyreCompound,
    WeatherState,
)


@dataclass
class LapRecord:
    """One completed lap, as observed -- not yet decomposed into effects.

    `lap_time_s` is measured as the wall-clock gap between this lap's first
    frame and the next lap's first frame (an approximation bounded by
    telemetry sample rate, not a timing-loop crossing). Decomposing this
    into base pace / fuel / degradation / track evolution / traffic effects
    is `backend/pace`'s and `backend/tyre`'s job (Phases 5-6), not this
    state's -- this record is their raw input.
    """

    lap: int
    lap_time_s: Optional[float]
    tyre_compound: Optional[TyreCompound]
    tyre_age_laps: Optional[int]
    fuel_load_kg_start: Optional[float]
    was_pit_lap: bool
    track_state_at_end: Optional[TrackState]
    avg_confidence: float

    def is_clean(self, min_confidence: float = 0.5) -> bool:
        """Basic robust-statistics usability check, shared by every
        consumer that fits something against lap times (backend/tyre,
        backend/pace) so "what counts as a usable lap" is defined once,
        not duplicated or drifting between modules. Deliberately minimal --
        a full "representative clean lap" model (traffic, incidents) is
        Phase 6's (backend/pace) job as its own intelligence output, not
        this predicate's.
        """

        return (
            self.lap_time_s is not None
            and not self.was_pit_lap
            and (self.track_state_at_end is None or self.track_state_at_end == TrackState.GREEN)
            and self.avg_confidence >= min_confidence
        )


@dataclass
class RaceState:
    car_id: str
    version: int = 0
    last_updated: Optional[datetime] = None
    latest_frame: Optional[RaceTelemetry] = None

    current_lap: int = 0
    current_lap_start_ts: Optional[datetime] = None
    current_sector: Optional[int] = None
    position: Optional[int] = None
    current_speed_kph: Optional[float] = None

    tyre_compound: Optional[TyreCompound] = None
    tyre_age_laps: Optional[int] = None
    # --- populated by Phase 5 (tyre degradation intelligence) ---
    estimated_degradation_s: Optional[float] = None
    degradation_rate_s_per_lap: Optional[float] = None
    degradation_acceleration_s_per_lap2: Optional[float] = None
    tyre_cliff_probability: Optional[float] = None
    remaining_tyre_life_laps: Optional[int] = None

    # --- populated by Phase 6 (pace intelligence) ---
    current_pace_s: Optional[float] = None
    expected_clean_pace_s: Optional[float] = None
    pace_delta_s: Optional[float] = None
    pace_trend_s_per_lap: Optional[float] = None
    # --- populated by Phase 15 (racing-line intelligence) ---
    racing_line_analysis: Optional["RacingLineAnalysis"] = None

    fuel_load_kg: Optional[float] = None

    gap_ahead_s: Optional[float] = None
    gap_behind_s: Optional[float] = None
    opponents_last_seen: dict[str, OpponentState] = field(default_factory=dict)
    # --- populated by Phase 14 (opponent intelligence) ---
    opponent_threats: dict[str, "OpponentSummary"] = field(default_factory=dict)

    weather: Optional[WeatherState] = None
    rain_probability: Optional[float] = None
    track_state: Optional[TrackState] = None
    safety_car: bool = False
    vsc: bool = False

    pit_status: Optional[PitStatus] = None
    pit_history: list[PitStop] = field(default_factory=list)

    # --- populated by Phase 7 (baseline trajectory) ---
    baseline_trajectory: Optional["BaselineTrajectory"] = None
    # --- populated by Phase 9/10 (strategy engine / compound selection) ---
    current_strategy: Optional["StrategyDecision"] = None
    # --- populated by Phase 11 (position / outcome prediction) ---
    predicted_finishing_position: Optional["PositionPrediction"] = None
    # --- populated by Phase 16 (radio intelligence) ---
    latest_radio_message: Optional["DriverRadioMessage"] = None
    radio_history: list["DriverRadioMessage"] = field(default_factory=list)

    confidence: float = 1.0

    completed_laps: list[LapRecord] = field(default_factory=list)

    def last_n_laps(self, n: int) -> list[LapRecord]:
        return self.completed_laps[-n:]
