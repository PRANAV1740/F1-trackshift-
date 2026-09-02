"""`RaceStateEstimator`: turns a stream of `NormalizationResult`s into a
continuously-updated `RaceState` per car.

Designed to be used directly as an `IngestionService` sink
(`service.add_sink(estimator.update)`) -- see backend/ingestion/service.py.
Every update is O(1) in the number of fields touched, never a recompute
over full history (Phase 4 requirement: "avoid unnecessary full
recomputation"). The one place history is consulted is lap-boundary
detection, which needs only the previous frame's lap number, already
available on the state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from backend.normalization.base import NormalizationResult
from backend.observability.logging import get_logger
from backend.state.race_state import LapRecord, RaceState

log = get_logger("state.estimator")


class RaceStateEstimator:
    def __init__(self):
        self._states: dict[str, RaceState] = {}
        self._lap_start_ts: dict[str, datetime] = {}
        self._lap_confidence_sum: dict[str, float] = {}
        self._lap_confidence_count: dict[str, int] = {}
        self._lap_had_pit: dict[str, bool] = {}

    def get_state(self, car_id: str) -> Optional[RaceState]:
        return self._states.get(car_id)

    def all_states(self) -> dict[str, RaceState]:
        return dict(self._states)

    def update(self, result: NormalizationResult) -> Optional[RaceState]:
        frame = result.normalized_frame
        if frame is None:
            log.debug("skipping dropped frame", extra={"fields": {"dropped_at_stage": result.dropped_at_stage}})
            return None

        car_id = frame.car_id
        state = self._states.get(car_id)
        if state is None:
            state = RaceState(car_id=car_id, current_lap=frame.lap)
            self._states[car_id] = state
            self._lap_start_ts[car_id] = frame.source_timestamp
            self._lap_confidence_sum[car_id] = 0.0
            self._lap_confidence_count[car_id] = 0
            self._lap_had_pit[car_id] = False

        if frame.lap > state.current_lap:
            self._finalize_lap(state, frame.source_timestamp)

        self._accumulate_lap_bookkeeping(car_id, frame)
        self._apply_frame(state, frame)
        return state

    def _accumulate_lap_bookkeeping(self, car_id: str, frame) -> None:
        if frame.sensor_confidence is not None:
            self._lap_confidence_sum[car_id] += frame.sensor_confidence.overall
            self._lap_confidence_count[car_id] += 1
        if frame.pit_status is not None and frame.pit_status.value != "ON_TRACK":
            self._lap_had_pit[car_id] = True

    def _finalize_lap(self, state: RaceState, new_lap_first_frame_ts: datetime) -> None:
        car_id = state.car_id
        lap_start = self._lap_start_ts.get(car_id)
        lap_time_s = (new_lap_first_frame_ts - lap_start).total_seconds() if lap_start else None

        count = self._lap_confidence_count.get(car_id, 0)
        avg_confidence = (self._lap_confidence_sum[car_id] / count) if count > 0 else 1.0

        state.completed_laps.append(
            LapRecord(
                lap=state.current_lap,
                lap_time_s=lap_time_s,
                tyre_compound=state.tyre_compound,
                tyre_age_laps=state.tyre_age_laps,
                was_pit_lap=self._lap_had_pit.get(car_id, False),
                track_state_at_end=state.track_state,
                avg_confidence=avg_confidence,
            )
        )

        self._lap_start_ts[car_id] = new_lap_first_frame_ts
        self._lap_confidence_sum[car_id] = 0.0
        self._lap_confidence_count[car_id] = 0
        self._lap_had_pit[car_id] = False

    def _apply_frame(self, state: RaceState, frame) -> None:
        state.version += 1
        state.last_updated = frame.ingest_timestamp or datetime.now(timezone.utc)
        state.latest_frame = frame

        state.current_lap = frame.lap
        state.current_sector = frame.sector
        state.position = frame.position
        state.current_speed_kph = frame.speed_kph

        state.tyre_compound = frame.tyre_compound
        state.tyre_age_laps = frame.tyre_age_laps

        state.fuel_load_kg = frame.fuel_load_kg

        state.gap_ahead_s = frame.gap_ahead_s
        state.gap_behind_s = frame.gap_behind_s
        for opponent in frame.opponent_states:
            state.opponents_last_seen[opponent.car_id] = opponent

        state.weather = frame.weather
        state.rain_probability = frame.rain_probability
        state.track_state = frame.track_state
        state.safety_car = frame.safety_car
        state.vsc = frame.vsc

        state.pit_status = frame.pit_status
        if frame.pit_history:
            known_laps = {p.lap for p in state.pit_history}
            for stop in frame.pit_history:
                if stop.lap not in known_laps:
                    state.pit_history.append(stop)

        if frame.sensor_confidence is not None:
            state.confidence = frame.sensor_confidence.overall
