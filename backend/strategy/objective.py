"""The strategy objective function, made explicit (never hidden).

    score(candidate) = projected_stint_time_s + risk_penalty_s + failure_penalty_s

Lower score wins. This is a direct instance of the documented pattern
"expected [race] time + risk penalty + failure probability penalty":

- `projected_stint_time_s` — sum of `backend/pace`'s per-lap projected
  pace over the candidate's remaining laps (reusing
  `project_pace_curve`, the same function `backend/state/baseline.py`
  uses for its own forward projection), plus pit loss if the candidate
  pits.
- `risk_penalty_s` — `RISK_UNCERTAINTY_WEIGHT * residual_std_s *
  sqrt(remaining_laps)`: the fitted curve's own residual uncertainty,
  scaled by the square root of the horizon it's extrapolated over (a
  standard way to reflect that uncertainty compounds over a longer
  projection, without overstating how fast it compounds -- variance sums
  additively for the errors accumulated over independent laps, so
  standard deviation scales with `sqrt(n)`). Zero when no fitted estimate
  exists for the candidate's compound (there is nothing to compute a
  residual from) -- that absence of information is instead reflected in
  `failure_penalty_s` and in the decision's `risks` list, not invented
  here as a fake number.
- `failure_penalty_s` — `cliff_probability_within(...) * CLIFF_FAILURE_COST_S`
  for a stay-out candidate whose tyre might hit its cliff within the
  comparison horizon; `NO_FITTED_CURVE_PENALTY_S` for a pit candidate onto
  a compound with no fitted degradation estimate yet this session (using
  the assumed fallback prior instead -- a real, if approximate, model, but
  one the objective treats as less trustworthy than a curve actually
  fitted from this car's own data).

See docs/STRATEGY.md for the full write-up and worked numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.pace.model import project_pace_curve
from backend.telemetry.schema import TyreCompound
from backend.tyre.model import DegradationEstimate

RISK_UNCERTAINTY_WEIGHT = 1.5
CLIFF_FAILURE_COST_S = 8.0
NO_FITTED_CURVE_PENALTY_S = 3.0

# A rough, commonly-cited QUALITATIVE prior for compound stiffness relative
# to MEDIUM -- NOT derived from any dataset, real or simulated, and
# deliberately not the same shape as simulator/generator/ground_truth.py's
# constants (this code must never import that module -- see
# backend/tyre/model.py's module docstring for why that separation matters).
# Used ONLY as a fallback when no fitted DegradationEstimate exists yet for
# a candidate compound this session.
ASSUMED_COMPOUND_RATE_MULTIPLIER: dict[TyreCompound, float] = {
    TyreCompound.SOFT: 1.6,
    TyreCompound.MEDIUM: 1.0,
    TyreCompound.HARD: 0.6,
    TyreCompound.INTERMEDIATE: 1.2,
    TyreCompound.WET: 1.0,
}


def fallback_degradation_estimate(compound: TyreCompound, reference: Optional[DegradationEstimate]) -> DegradationEstimate:
    """A degradation curve for a compound this car hasn't run yet this
    session, scaled from whatever curve IS fitted (or a generic default if
    none is) via `ASSUMED_COMPOUND_RATE_MULTIPLIER`. Always flagged to
    callers as a fallback via `NO_FITTED_CURVE_PENALTY_S` in the objective,
    never presented with the same confidence as a real fit.
    """

    multiplier = ASSUMED_COMPOUND_RATE_MULTIPLIER.get(compound, 1.0)
    if reference is not None:
        reference_multiplier = ASSUMED_COMPOUND_RATE_MULTIPLIER.get(reference.compound, 1.0)
        scale = multiplier / reference_multiplier
        return DegradationEstimate(
            compound=compound,
            n_observations=0,
            base_pace_s=reference.base_pace_s,
            degradation_rate_s_per_lap=reference.degradation_rate_s_per_lap * scale,
            cliff_lap=reference.cliff_lap,
            cliff_coefficient_s_per_lap2=reference.cliff_coefficient_s_per_lap2 * scale,
            residual_std_s=reference.residual_std_s * 1.5,  # extra uncertainty for an unfitted extrapolation
        )
    return DegradationEstimate(
        compound=compound,
        n_observations=0,
        base_pace_s=90.0,  # generic placeholder pace; only relative comparisons across candidates matter here
        degradation_rate_s_per_lap=0.03 * multiplier,
        cliff_lap=20,
        cliff_coefficient_s_per_lap2=0.01 * multiplier,
        residual_std_s=1.0,
    )


@dataclass
class CandidateScore:
    label: str
    compound: Optional[TyreCompound]
    pits: bool
    projected_stint_time_s: float
    risk_penalty_s: float
    failure_penalty_s: float
    used_fallback_curve: bool
    degradation_estimate: Optional[DegradationEstimate]

    @property
    def total_score_s(self) -> float:
        return self.projected_stint_time_s + self.risk_penalty_s + self.failure_penalty_s


def score_stay_out(
    degradation_estimate: Optional[DegradationEstimate],
    base_pace_s: Optional[float],
    current_lap: int,
    current_age_laps: int,
    current_fuel_kg: float,
    fuel_burn_rate_kg_per_lap: float,
    remaining_laps: int,
) -> CandidateScore:
    if degradation_estimate is None or base_pace_s is None or remaining_laps <= 0:
        return CandidateScore("STAY_OUT", None, False, 0.0, 0.0, 0.0, used_fallback_curve=True, degradation_estimate=None)

    curve = project_pace_curve(
        base_pace_s, degradation_estimate, current_lap, current_age_laps, current_fuel_kg, fuel_burn_rate_kg_per_lap, remaining_laps
    )
    projected_time = sum(p for p in curve if p is not None)

    risk = RISK_UNCERTAINTY_WEIGHT * degradation_estimate.residual_std_s * (remaining_laps**0.5)
    failure = degradation_estimate.cliff_probability_within(current_age_laps + remaining_laps, lookahead_laps=0) * CLIFF_FAILURE_COST_S

    return CandidateScore(
        "STAY_OUT", degradation_estimate.compound, False, projected_time, risk, failure,
        used_fallback_curve=False, degradation_estimate=degradation_estimate,
    )


def score_pit(
    compound: TyreCompound,
    fitted_estimate: Optional[DegradationEstimate],
    reference_estimate: Optional[DegradationEstimate],
    base_pace_s: Optional[float],
    current_lap: int,
    current_fuel_kg: float,
    fuel_burn_rate_kg_per_lap: float,
    remaining_laps: int,
    pit_loss_s: float,
) -> CandidateScore:
    """`remaining_laps` must be the SAME remaining-race-distance horizon
    passed to `score_stay_out` -- pitting does not skip a lap of race
    distance, it adds `pit_loss_s` on top of otherwise covering the same
    number of laps (the in/out lap is approximated as running at ordinary
    fresh-tyre pace, with `pit_loss_s` capturing the extra time the pit
    lane/stop itself costs). An earlier version passed `remaining_laps - 1`
    here to "avoid double counting the pit lap", which instead made every
    PIT candidate systematically cheaper than STAY_OUT by roughly one lap's
    pace minus the pit loss -- caught by
    tests/test_strategy_engine.py::test_healthy_fresh_tyre_over_a_short_remaining_distance_stays_out
    recommending PIT for a fresh, healthy tyre with 7 laps left in the
    race. See docs/VALIDATION.md for the full account.
    """

    used_fallback = fitted_estimate is None
    estimate = fitted_estimate or fallback_degradation_estimate(compound, reference_estimate)
    pace = base_pace_s if base_pace_s is not None else estimate.base_pace_s

    if remaining_laps <= 0:
        return CandidateScore(
            f"PIT->{compound.value}", compound, True, pit_loss_s, 0.0,
            NO_FITTED_CURVE_PENALTY_S if used_fallback else 0.0, used_fallback, estimate,
        )

    curve = project_pace_curve(pace, estimate, current_lap, 0, current_fuel_kg, fuel_burn_rate_kg_per_lap, remaining_laps)
    projected_time = pit_loss_s + sum(p for p in curve if p is not None)

    risk = RISK_UNCERTAINTY_WEIGHT * estimate.residual_std_s * (remaining_laps**0.5)
    failure = NO_FITTED_CURVE_PENALTY_S if used_fallback else 0.0

    return CandidateScore(f"PIT->{compound.value}", compound, True, projected_time, risk, failure, used_fallback, estimate)
