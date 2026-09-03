"""Clean-lap pace estimation.

Answers: what pace is this car actually doing right now, what pace
*should* it be doing on a clean lap given current tyre/fuel/track state,
and how do those two compare? All three numbers, plus a short recent-trend
slope, are returned together in `PaceEstimate` with an inspectable
`contributions` breakdown -- never a single opaque "pace" number.

When a fitted `DegradationEstimate` is available from `backend/tyre`,
expected clean pace is computed by evaluating that decomposition (base
pace + assumed fuel effect + assumed track evolution + fitted degradation)
at the car's *current* age/fuel/lap -- reusing Phase 5's fit rather than
re-deriving it. Early in a stint, before enough laps exist for that fit,
this falls back to a simple rolling average of recent clean laps -- a
weaker but always-available estimate, clearly labeled as such via
`PaceEstimate.source`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from backend.state.race_state import LapRecord
from backend.tyre.model import DegradationEstimate, assumed_fuel_effect_s, assumed_track_evolution_gain_s

MIN_CONFIDENCE_FOR_CLEAN_LAP = 0.5
TREND_WINDOW_LAPS = 5
MIN_LAPS_FOR_TREND = 3


@dataclass
class PaceEstimate:
    current_pace_s: Optional[float]
    expected_clean_pace_s: Optional[float]
    pace_delta_s: Optional[float]
    pace_trend_s_per_lap: Optional[float]
    source: str  # "tyre_model" | "rolling_average" | "insufficient_data"
    contributions: dict = field(default_factory=dict)


def project_pace_curve(
    base_pace_s: float,
    degradation_estimate: Optional[DegradationEstimate],
    start_lap: int,
    start_age_laps: int,
    start_fuel_kg: float,
    fuel_burn_rate_kg_per_lap: float,
    n_laps: int,
) -> list[Optional[float]]:
    """Per-lap projected pace for `n_laps` laps starting after `start_lap`,
    assuming no pit stop and no condition change (the definition of a
    baseline projection). Shared by `backend/state/baseline.py` (Phase 7)
    and `backend/strategy` (Phase 9) so the two don't duplicate this loop --
    a strategy candidate's projected stint time and the baseline's forward
    projection are the same computation at different horizons.

    Returns `None` for every lap if `degradation_estimate` is `None` --
    callers decide their own fallback (e.g. a rolling average), this
    function only knows the model-based projection.
    """

    if degradation_estimate is None:
        return [None] * n_laps

    curve: list[Optional[float]] = []
    for offset in range(1, n_laps + 1):
        lap = start_lap + offset
        age = start_age_laps + offset
        fuel = max(start_fuel_kg - fuel_burn_rate_kg_per_lap * offset, 0.0)
        pace = (
            base_pace_s
            + assumed_fuel_effect_s(fuel)
            + assumed_track_evolution_gain_s(lap)
            + degradation_estimate.degradation_at(age)
        )
        curve.append(pace)
    return curve


def estimate_pace(
    completed_laps: list[LapRecord],
    current_lap: int,
    current_tyre_age_laps: Optional[int],
    current_fuel_load_kg: Optional[float],
    degradation_estimate: Optional[DegradationEstimate],
) -> PaceEstimate:
    if not completed_laps:
        return PaceEstimate(None, None, None, None, "insufficient_data")

    current_pace_s = completed_laps[-1].lap_time_s

    clean_laps = [lap for lap in completed_laps if lap.is_clean(MIN_CONFIDENCE_FOR_CLEAN_LAP)]
    recent_clean = clean_laps[-TREND_WINDOW_LAPS:]

    pace_trend_s_per_lap = None
    if len(recent_clean) >= MIN_LAPS_FOR_TREND:
        xs = np.array([lap.lap for lap in recent_clean], dtype=float)
        ys = np.array([lap.lap_time_s for lap in recent_clean], dtype=float)
        slope, _intercept = np.polyfit(xs, ys, 1)
        pace_trend_s_per_lap = float(slope)

    expected_clean_pace_s: Optional[float] = None
    contributions: dict = {}
    source = "insufficient_data"

    if degradation_estimate is not None and current_tyre_age_laps is not None and current_fuel_load_kg is not None:
        fuel_effect = assumed_fuel_effect_s(current_fuel_load_kg)
        track_evolution = assumed_track_evolution_gain_s(current_lap)
        degradation = degradation_estimate.degradation_at(current_tyre_age_laps)
        expected_clean_pace_s = degradation_estimate.base_pace_s + fuel_effect + track_evolution + degradation
        contributions = {
            "base_pace_s": degradation_estimate.base_pace_s,
            "fuel_effect_s": fuel_effect,
            "track_evolution_s": track_evolution,
            "degradation_s": degradation,
        }
        source = "tyre_model"
    elif recent_clean:
        expected_clean_pace_s = float(np.mean([lap.lap_time_s for lap in recent_clean]))
        contributions = {"rolling_average_s": expected_clean_pace_s, "n_laps": len(recent_clean)}
        source = "rolling_average"

    pace_delta_s = None
    if current_pace_s is not None and expected_clean_pace_s is not None:
        pace_delta_s = current_pace_s - expected_clean_pace_s

    return PaceEstimate(
        current_pace_s=current_pace_s,
        expected_clean_pace_s=expected_clean_pace_s,
        pace_delta_s=pace_delta_s,
        pace_trend_s_per_lap=pace_trend_s_per_lap,
        source=source,
        contributions=contributions,
    )
