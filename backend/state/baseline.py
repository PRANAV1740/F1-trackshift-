"""Baseline race trajectory: "if current conditions continue, what happens?"

A continuously-updated forward projection, not a Monte-Carlo or
multi-scenario simulation -- the architecture is one maintained baseline
that gets compared against as new events arrive (Phase 8's job), not "run
N counterfactual races". Recomputed on lap completion (event-driven), same
as `backend/tyre` and `backend/pace`.

Future pace and tyre state are genuine projections built on Phase 5's
fitted degradation curve and Phase 6's pace decomposition -- assuming no
pit stop and no condition change, since that IS the definition of a
baseline. Position, gaps, and finishing outcome are, honestly, a **naive**
carry-forward of the current values (see `NAIVE_BASELINE_NOTE`) -- a real
forecast needs opponent modeling (Phase 14) and a position-outcome model
(Phase 11), neither of which exists yet. Labeling this explicitly as naive,
rather than presenting it with the same confidence as the pace/tyre
projection, is the honest choice given what's actually built so far.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backend.pace.model import PaceEstimate, project_pace_curve
from backend.state.race_state import RaceState
from backend.tyre.model import DegradationEstimate

DEFAULT_HORIZON_LAPS = 10
DEFAULT_ASSUMED_FUEL_BURN_KG_PER_LAP = 1.8  # used only when no observed history exists yet
PIT_WINDOW_BUFFER_LAPS = 2
NAIVE_BASELINE_NOTE = (
    "position/gap/finish fields are a naive carry-forward of current values, "
    "not a modeled forecast -- that requires Phase 11 (position prediction) "
    "and Phase 14 (opponent intelligence), neither implemented yet"
)


@dataclass
class BaselineProjectionPoint:
    lap: int
    projected_tyre_age_laps: int
    projected_fuel_load_kg: float
    projected_pace_s: Optional[float]
    projected_degradation_s: Optional[float]


@dataclass
class BaselineTrajectory:
    generated_at_lap: int
    horizon_laps: int
    projection: list[BaselineProjectionPoint] = field(default_factory=list)
    recommended_pit_window: Optional[tuple[int, int]] = None
    naive_position: Optional[int] = None
    naive_gap_ahead_s: Optional[float] = None
    naive_gap_behind_s: Optional[float] = None
    method_note: str = NAIVE_BASELINE_NOTE


def estimate_fuel_burn_rate(state: RaceState) -> float:
    if len(state.completed_laps) >= 1 and state.completed_laps[0].fuel_load_kg_start is not None:
        first_fuel = state.completed_laps[0].fuel_load_kg_start
        laps_elapsed = max(state.current_lap - state.completed_laps[0].lap, 1)
        if state.fuel_load_kg is not None:
            observed = (first_fuel - state.fuel_load_kg) / laps_elapsed
            if observed > 0:
                return observed
    return DEFAULT_ASSUMED_FUEL_BURN_KG_PER_LAP


def build_baseline_trajectory(
    state: RaceState,
    degradation_estimate: Optional[DegradationEstimate],
    pace_estimate: Optional[PaceEstimate],
    horizon_laps: int = DEFAULT_HORIZON_LAPS,
) -> BaselineTrajectory:
    fuel_burn_rate = estimate_fuel_burn_rate(state)
    current_age = state.tyre_age_laps or 0
    current_fuel = state.fuel_load_kg if state.fuel_load_kg is not None else 0.0
    base_pace = degradation_estimate.base_pace_s if degradation_estimate is not None else (
        pace_estimate.expected_clean_pace_s if pace_estimate is not None else None
    )

    pace_curve = (
        project_pace_curve(
            base_pace_s=base_pace,
            degradation_estimate=degradation_estimate,
            start_lap=state.current_lap,
            start_age_laps=current_age,
            start_fuel_kg=current_fuel,
            fuel_burn_rate_kg_per_lap=fuel_burn_rate,
            n_laps=horizon_laps,
        )
        if base_pace is not None
        else [None] * horizon_laps
    )

    projection: list[BaselineProjectionPoint] = []
    for offset in range(1, horizon_laps + 1):
        future_lap = state.current_lap + offset
        future_age = current_age + offset
        future_fuel = max(current_fuel - fuel_burn_rate * offset, 0.0)
        projected_pace = pace_curve[offset - 1]
        projected_degradation = degradation_estimate.degradation_at(future_age) if degradation_estimate is not None else None

        projection.append(
            BaselineProjectionPoint(
                lap=future_lap,
                projected_tyre_age_laps=future_age,
                projected_fuel_load_kg=future_fuel,
                projected_pace_s=projected_pace,
                projected_degradation_s=projected_degradation,
            )
        )

    recommended_pit_window = None
    if degradation_estimate is not None:
        remaining = degradation_estimate.remaining_competitive_life_laps(current_age)
        if remaining is not None:
            end = state.current_lap + remaining
            start = max(end - PIT_WINDOW_BUFFER_LAPS, state.current_lap + 1)
            recommended_pit_window = (start, end)

    return BaselineTrajectory(
        generated_at_lap=state.current_lap,
        horizon_laps=horizon_laps,
        projection=projection,
        recommended_pit_window=recommended_pit_window,
        naive_position=state.position,
        naive_gap_ahead_s=state.gap_ahead_s,
        naive_gap_behind_s=state.gap_behind_s,
    )
