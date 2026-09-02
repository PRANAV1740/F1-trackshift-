"""Tyre degradation estimation -- the official TrackShift 2026 problem.

The forbidden shortcut is `lap_time_delta == tyre_degradation`. This module
decomposes lap time as:

    lap_time = base_pace + fuel_effect + track_evolution + degradation + noise

and estimates the degradation component specifically. `fuel_effect` and
`track_evolution` are applied via a small, fixed, documented ASSUMED model
(`assumed_fuel_effect_s`, `assumed_track_evolution_gain_s` below) rather
than fit from data. This is a deliberate identifiability choice, not
laziness -- see "Why fuel/evolution are assumed, not fit" below. Only the
degradation curve is actually estimated, via weighted least squares on
lap-time residual after removing the assumed effects.

## Why fuel/evolution are assumed, not fit

Within a single, uninterrupted stint (no pit stop), tyre age, lap number,
fuel burned, and track evolution are all deterministic, near-linear
functions of the same lap counter -- they are close to perfectly
collinear. A regression asked to freely fit coefficients for all of them
simultaneously from single-stint data cannot separate them; this is a
textbook identifiability problem, not an implementation bug. In real
racing this is resolved by pooling data across multiple stints/pit
strategies, where different cars/stints reach the same lap number at
different tyre ages, breaking the collinearity.

For a single-stint-capable prototype, this module instead treats fuel
effect and track evolution as known, physically-reasonable assumed
functions (documented, and deliberately NOT numerically identical to
`simulator/generator/ground_truth.py`'s constants -- this model must never
import that module; it validates against it only from test code, never
sees its exact values, and the difference in assumed vs. true constants is
itself part of what Phase 20 backtesting should surface as a source of
residual bias). With those two effects removed, only ONE unknown curve
remains to fit against age: degradation. That is identifiable from a
single stint.

**Documented limitation:** because fuel and evolution are assumed rather
than fit, any error in those assumptions leaks into the degradation
estimate as bias, and "driver variation" (a confound this module does not
model at all) leaks into the residual as noise, widening
`residual_std_s`. Both are acknowledged limitations, not hidden ones -- see
docs/VALIDATION.md for how large that bias turns out to be against known
synthetic ground truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from backend.telemetry.schema import TyreCompound

# --- Assumed (not fit) fuel/track-evolution physics -------------------------
# Deliberately different from simulator/generator/ground_truth.py's constants
# -- see module docstring. Rough orders of magnitude commonly cited for
# fuel effect in single-seater racing; not derived from any real dataset.

ASSUMED_FUEL_EFFECT_S_PER_KG = 0.030
ASSUMED_EVOLUTION_SATURATION_LAP = 15
ASSUMED_EVOLUTION_MAX_GAIN_S = 0.6


def assumed_fuel_effect_s(fuel_load_kg: float) -> float:
    return ASSUMED_FUEL_EFFECT_S_PER_KG * max(fuel_load_kg, 0.0)


def assumed_track_evolution_gain_s(lap: int) -> float:
    progress = min(max(lap, 0), ASSUMED_EVOLUTION_SATURATION_LAP) / ASSUMED_EVOLUTION_SATURATION_LAP
    return -ASSUMED_EVOLUTION_MAX_GAIN_S * progress


# --- Inputs -------------------------------------------------------------------


@dataclass(frozen=True)
class TyreObservation:
    """One completed, usable lap -- the input to fitting."""

    lap: int
    tyre_age_laps: int
    compound: TyreCompound
    fuel_load_kg: float
    lap_time_s: float
    confidence: float = 1.0


# --- Output --------------------------------------------------------------------


@dataclass
class DegradationEstimate:
    """Everything Phase 4's RaceState fields need, in one object.

    `cliff_posterior` is a discrete probability distribution over candidate
    cliff laps (see `fit_degradation_model`'s docstring for how it's
    derived) -- it is the basis for `cliff_probability_within`, and is
    exposed directly for anyone who wants the full distribution rather than
    a single collapsed probability.
    """

    compound: TyreCompound
    n_observations: int
    base_pace_s: float
    degradation_rate_s_per_lap: float
    cliff_lap: Optional[int]
    cliff_coefficient_s_per_lap2: float
    residual_std_s: float
    cliff_posterior: dict[int, float] = field(default_factory=dict)

    def degradation_at(self, age_laps: int) -> float:
        if age_laps <= 0:
            return 0.0
        linear = self.degradation_rate_s_per_lap * age_laps
        cliff = 0.0
        if self.cliff_lap is not None:
            excess = max(0, age_laps - self.cliff_lap)
            cliff = self.cliff_coefficient_s_per_lap2 * (excess**2)
        return linear + cliff

    def degradation_rate_at(self, age_laps: int) -> float:
        rate = self.degradation_rate_s_per_lap
        if self.cliff_lap is not None and age_laps > self.cliff_lap:
            rate += 2 * self.cliff_coefficient_s_per_lap2 * (age_laps - self.cliff_lap)
        return rate

    def degradation_acceleration_at(self, age_laps: int) -> float:
        if self.cliff_lap is not None and age_laps > self.cliff_lap:
            return 2 * self.cliff_coefficient_s_per_lap2
        return 0.0

    def cliff_probability_within(self, age_laps: int, lookahead_laps: int = 3) -> float:
        """P(the fitted cliff lap is at or before age_laps + lookahead_laps)."""

        if not self.cliff_posterior:
            return 0.0
        return sum(w for cliff, w in self.cliff_posterior.items() if cliff <= age_laps + lookahead_laps)

    def remaining_competitive_life_laps(
        self, age_laps: int, max_acceptable_extra_penalty_s: float = 1.5, horizon_laps: int = 40
    ) -> Optional[int]:
        """Additional laps until cumulative extra degradation exceeds a threshold.

        `None` means the threshold is not reached within `horizon_laps` --
        i.e. "this tyre isn't the binding constraint for the foreseeable race."
        """

        current = self.degradation_at(age_laps)
        for extra in range(0, horizon_laps + 1):
            if self.degradation_at(age_laps + extra) - current > max_acceptable_extra_penalty_s:
                return extra
        return None


# --- Fitting -------------------------------------------------------------------

MIN_OBSERVATIONS = 4
_CANDIDATE_CLIFF_LAPS = list(range(3, 45))


def fit_degradation_model(observations: list[TyreObservation]) -> Optional[DegradationEstimate]:
    """Weighted least squares of (lap_time - assumed_fuel - assumed_evolution)
    against tyre age, with the cliff lap chosen by grid search over
    candidate values (a simple, fully interpretable form of piecewise
    regression -- no black-box model needed for this).

    `cliff_posterior` treats each candidate cliff's residual sum of squares
    as an (unnormalized) Gaussian negative log-likelihood, exactly the
    standard argument for why minimizing RSS is the maximum-likelihood
    estimate under i.i.d. Gaussian noise: likelihood ∝ exp(-RSS / 2σ²), so
    `softmax(-RSS / 2σ²)` over the candidate grid is the (uniform-prior)
    posterior over which candidate is correct. This is genuinely
    Bayesian in spirit, not just a heuristic score -- but it does inherit
    the Gaussian-residual assumption, which is an approximation like any
    other; see docs/MODELS.md.

    Returns `None` if there isn't enough data for this compound
    (`MIN_OBSERVATIONS`) -- callers should treat that as "not enough
    information yet," not as an error.
    """

    if len(observations) < MIN_OBSERVATIONS:
        return None

    compound = observations[0].compound
    ages = np.array([o.tyre_age_laps for o in observations], dtype=float)
    weights = np.array([max(o.confidence, 0.05) for o in observations], dtype=float)
    residual_targets = np.array(
        [o.lap_time_s - assumed_fuel_effect_s(o.fuel_load_kg) - assumed_track_evolution_gain_s(o.lap) for o in observations],
        dtype=float,
    )

    sqrt_w = np.sqrt(weights)
    best: Optional[tuple[float, int, np.ndarray]] = None
    rss_by_cliff: dict[int, float] = {}

    for cliff in _CANDIDATE_CLIFF_LAPS:
        hinge = np.clip(ages - cliff, 0, None) ** 2
        design = np.column_stack([np.ones_like(ages), ages, hinge])
        weighted_design = design * sqrt_w[:, None]
        weighted_target = residual_targets * sqrt_w
        try:
            beta, *_ = np.linalg.lstsq(weighted_design, weighted_target, rcond=None)
        except np.linalg.LinAlgError:
            continue
        predicted = design @ beta
        rss = float(np.sum(weights * (residual_targets - predicted) ** 2))
        rss_by_cliff[cliff] = rss
        if best is None or rss < best[0]:
            best = (rss, cliff, beta)

    if best is None:
        return None

    rss, cliff_lap, beta = best
    base_pace, degradation_rate, cliff_coeff = (float(x) for x in beta)

    dof = max(len(observations) - 3, 1)
    residual_std = math.sqrt(max(rss / dof, 0.0))

    min_rss = min(rss_by_cliff.values())
    sigma2 = max(min_rss / dof, 1e-6)
    raw = {c: math.exp(-(r - min_rss) / (2 * sigma2)) for c, r in rss_by_cliff.items()}
    total = sum(raw.values()) or 1.0
    posterior = {c: w / total for c, w in raw.items()}

    return DegradationEstimate(
        compound=compound,
        n_observations=len(observations),
        base_pace_s=base_pace,
        degradation_rate_s_per_lap=degradation_rate,
        cliff_lap=cliff_lap,
        cliff_coefficient_s_per_lap2=cliff_coeff,
        residual_std_s=residual_std,
        cliff_posterior=posterior,
    )
