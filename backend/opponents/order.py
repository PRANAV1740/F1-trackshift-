"""Race order/gap computation across multiple cars.

The only thing about "position" that genuinely needs multi-car awareness
-- everything else about an opponent (their compound, tyre age, pace,
degradation) is already computed per-car by Phases 4-6, since
`RaceStateEstimator`/`TyreDegradationEstimator`/`PaceIntelligenceEstimator`
are all already keyed by `car_id`. `RaceState.position`/`gap_ahead_s`/
`gap_behind_s` as set by `RaceStateEstimator` come straight off the raw
telemetry frame (a static `starting_position` in this prototype's
single-car generator, since nothing computes it dynamically) --
`RaceOrderTracker.apply()` OVERWRITES those fields with a real,
continuously-updated ranking once more than one car is being tracked.

**Method, and its documented approximation:** each car's race progress is
estimated as `current_lap + (elapsed time since this lap started) /
(this car's own current expected lap time)` -- a continuous, monotonic
proxy for race distance covered, without needing sub-lap position data
(the common schema only has 3-way sector resolution, not continuous
distance). Cars are ranked by this progress; the time gap between
adjacent cars is `(their progress - this car's progress) × an expected lap
time` -- using the SLOWER car's own expected lap time gives a defensible
(not exact) time value. This is accurate to within roughly a sector's
worth of resolution, not to the sub-second precision a real timing loop
would give -- a documented, hackathon-grade approximation, not a claim of
timing-loop accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.state.race_state import RaceState

DEFAULT_LAP_TIME_ESTIMATE_S = 90.0


@dataclass
class RaceProgress:
    car_id: str
    lap: int
    progress_fraction: float
    absolute_progress: float
    expected_lap_time_s: float


def _expected_lap_time_s(state: RaceState) -> float:
    return state.current_pace_s or state.expected_clean_pace_s or DEFAULT_LAP_TIME_ESTIMATE_S


class RaceOrderTracker:
    def __init__(self):
        self._progress: dict[str, RaceProgress] = {}

    def update(self, state: RaceState) -> None:
        expected_lap_s = max(_expected_lap_time_s(state), 1.0)
        fraction = 0.0
        if state.current_lap_start_ts is not None and state.latest_frame is not None:
            # `current_lap_start_ts` is always derived from `source_timestamp`
            # (RaceStateEstimator sets it that way) -- comparing it against
            # `ingest_timestamp` (real wall-clock time) here would mix two
            # different time domains, exactly the deterministic-anchor-vs-
            # real-time bug already documented and fixed once in
            # backend/adapters/simulator_adapter.py. Comparing like with
            # like: source_timestamp against source_timestamp. Found via
            # this tracker returning an elapsed time of ~244 *days* in a
            # multi-car test -- see docs/VALIDATION.md.
            now = state.latest_frame.source_timestamp
            elapsed_s = (now - state.current_lap_start_ts).total_seconds()
            fraction = min(max(elapsed_s / expected_lap_s, 0.0), 0.999)

        self._progress[state.car_id] = RaceProgress(
            car_id=state.car_id,
            lap=state.current_lap,
            progress_fraction=fraction,
            absolute_progress=state.current_lap + fraction,
            expected_lap_time_s=expected_lap_s,
        )

    def order(self) -> list[RaceProgress]:
        return sorted(self._progress.values(), key=lambda p: -p.absolute_progress)

    def gap_seconds(self, from_car_id: str, to_car_id: str) -> Optional[float]:
        """Signed time gap: positive means `to_car_id` is ahead of `from_car_id`.

        Uses `from_car_id`'s own expected lap time to convert the progress
        difference into seconds (same convention as `apply()`), so this is
        directly comparable to `RaceState.gap_ahead_s`/`gap_behind_s` for
        adjacent cars, and is additionally defined for non-adjacent pairs
        (which those two fields, by definition, are not).
        """

        a = self._progress.get(from_car_id)
        b = self._progress.get(to_car_id)
        if a is None or b is None:
            return None
        return (b.absolute_progress - a.absolute_progress) * a.expected_lap_time_s

    def apply(self, states: dict[str, RaceState]) -> None:
        """Overwrite position/gap_ahead_s/gap_behind_s on every tracked
        car's state, given the current standings. Call after updating
        every car's RaceState for this synchronization point."""

        ranked = self.order()
        for idx, progress in enumerate(ranked):
            state = states.get(progress.car_id)
            if state is None:
                continue
            state.position = idx + 1

            if idx > 0:
                ahead = ranked[idx - 1]
                state.gap_ahead_s = (ahead.absolute_progress - progress.absolute_progress) * progress.expected_lap_time_s
            else:
                state.gap_ahead_s = None

            if idx < len(ranked) - 1:
                behind = ranked[idx + 1]
                state.gap_behind_s = (progress.absolute_progress - behind.absolute_progress) * progress.expected_lap_time_s
            else:
                state.gap_behind_s = None
