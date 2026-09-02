"""`TyreDegradationEstimator`: wires `backend/tyre/model.py` into `RaceState`.

Designed the same way as `backend/state/estimator.py`: cheap to call after
every frame (`update(state)`), but the actual (re)fit only happens when
`state.completed_laps` has grown -- an event-driven refit on lap
completion, not a per-tick recomputation (Phase 4/7's stated performance
requirement applies here too).

Filters obviously-unusable laps before they ever reach the regression
(basic robust-statistics practice: exclude pit laps, laps not run under
green-flag conditions, and low-confidence laps). This is deliberately
minimal -- a full "what counts as a representative clean lap" model is
Phase 6's job (Pace Intelligence); this is just enough filtering that
Phase 5 doesn't have to wait on Phase 6 to produce a sane estimate.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from backend.observability.logging import get_logger
from backend.state.race_state import LapRecord, RaceState
from backend.telemetry.schema import TyreCompound
from backend.tyre.model import DegradationEstimate, TyreObservation, fit_degradation_model

log = get_logger("tyre.estimator")

MIN_CONFIDENCE_TO_USE_LAP = 0.5


def _is_usable(lap_record: LapRecord) -> bool:
    """General usability (`LapRecord.is_clean`, shared with `backend/pace`)
    plus tyre-specific requirements: the fields the degradation regression
    actually needs (compound, age, fuel) must be present."""

    return (
        lap_record.is_clean(MIN_CONFIDENCE_TO_USE_LAP)
        and lap_record.tyre_compound is not None
        and lap_record.tyre_age_laps is not None
        and lap_record.fuel_load_kg_start is not None
    )


class TyreDegradationEstimator:
    def __init__(self):
        self._observations: dict[tuple[str, TyreCompound], list[TyreObservation]] = defaultdict(list)
        self._estimates: dict[tuple[str, TyreCompound], DegradationEstimate] = {}
        self._seen_lap_count: dict[str, int] = {}

    def get_estimate(self, car_id: str, compound: TyreCompound) -> Optional[DegradationEstimate]:
        return self._estimates.get((car_id, compound))

    def update(self, state: RaceState) -> None:
        seen = self._seen_lap_count.get(state.car_id, 0)
        new_laps = state.completed_laps[seen:]
        self._seen_lap_count[state.car_id] = len(state.completed_laps)

        refit_keys: set[tuple[str, TyreCompound]] = set()
        for lap_record in new_laps:
            if not _is_usable(lap_record):
                continue
            observation = TyreObservation(
                lap=lap_record.lap,
                tyre_age_laps=lap_record.tyre_age_laps,
                compound=lap_record.tyre_compound,
                fuel_load_kg=lap_record.fuel_load_kg_start,
                lap_time_s=lap_record.lap_time_s,
                confidence=lap_record.avg_confidence,
            )
            key = (state.car_id, lap_record.tyre_compound)
            self._observations[key].append(observation)
            refit_keys.add(key)

        for key in refit_keys:
            estimate = fit_degradation_model(self._observations[key])
            if estimate is not None:
                self._estimates[key] = estimate
                log.info(
                    "tyre degradation model refit",
                    extra={
                        "fields": {
                            "car_id": key[0],
                            "compound": key[1].value,
                            "n_observations": estimate.n_observations,
                            "degradation_rate_s_per_lap": round(estimate.degradation_rate_s_per_lap, 4),
                            "cliff_lap": estimate.cliff_lap,
                        }
                    },
                )

        self._apply_to_state(state)

    def _apply_to_state(self, state: RaceState) -> None:
        if state.tyre_compound is None or state.tyre_age_laps is None:
            return
        estimate = self._estimates.get((state.car_id, state.tyre_compound))
        if estimate is None:
            return

        age = state.tyre_age_laps
        state.estimated_degradation_s = estimate.degradation_at(age)
        state.degradation_rate_s_per_lap = estimate.degradation_rate_at(age)
        state.degradation_acceleration_s_per_lap2 = estimate.degradation_acceleration_at(age)
        state.tyre_cliff_probability = estimate.cliff_probability_within(age)
        state.remaining_tyre_life_laps = estimate.remaining_competitive_life_laps(age)
