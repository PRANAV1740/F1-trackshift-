"""Monte Carlo finishing-position prediction.

Not a lap-time predictor -- a *position distribution* predictor, per the
problem statement: given this car's projected remaining-race-time
distribution and each known opponent's, sample both many times and rank
the draws to get an empirical probability for every possible finishing
position. Every number traces back to an actual simulation; nothing here
is a hand-picked percentage.

**This is honestly gated on having opponent data.** The current simulator
(Phase 2/18) produces a single car, so `RaceState.opponents_last_seen` is
empty in live usage today -- `predict_position()` reports
`source="insufficient_opponent_data"` rather than fabricating a plausible-
looking distribution from nothing. The Monte Carlo machinery itself is
real and validated (`tests/test_prediction_model.py`, using synthetic
multi-opponent fixtures) so it's ready the moment Phase 14 (opponent
intelligence) starts populating real opponent time distributions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

DEFAULT_N_SIMULATIONS = 5000
MIN_STD_S = 1e-6


@dataclass(frozen=True)
class TimeDistribution:
    """A car's projected remaining-race-time, as a Normal(mean, std).

    `std_s` should reflect genuine uncertainty (e.g. a fitted degradation
    curve's `residual_std_s * sqrt(remaining_laps)` -- see
    `backend/strategy/objective.py`'s risk-penalty derivation for why that
    scaling is the right one for summed per-lap residuals), not an
    arbitrary guess.
    """

    car_id: str
    mean_s: float
    std_s: float


@dataclass
class PositionPrediction:
    car_id: str
    lap: int
    source: str  # "monte_carlo" | "insufficient_opponent_data"
    position_probabilities: dict[int, float] = field(default_factory=dict)
    expected_position: Optional[float] = None
    position_gain_expected: Optional[float] = None
    risk_of_losing_positions: Optional[float] = None
    n_simulations: int = 0
    note: str = ""


def predict_position(
    own: TimeDistribution,
    opponents: list[TimeDistribution],
    current_position: int,
    lap: int,
    n_simulations: int = DEFAULT_N_SIMULATIONS,
    seed: int = 42,
) -> PositionPrediction:
    if not opponents:
        return PositionPrediction(
            car_id=own.car_id,
            lap=lap,
            source="insufficient_opponent_data",
            note="No opponent time distributions available -- needs Phase 14 (opponent intelligence). "
            "Cannot honestly produce a position distribution from zero opponents.",
        )

    rng = np.random.default_rng(seed)
    own_samples = rng.normal(own.mean_s, max(own.std_s, MIN_STD_S), n_simulations)

    finish_positions = np.ones(n_simulations, dtype=int)
    for opponent in opponents:
        opponent_samples = rng.normal(opponent.mean_s, max(opponent.std_s, MIN_STD_S), n_simulations)
        finish_positions += (opponent_samples < own_samples).astype(int)

    counts = Counter(finish_positions.tolist())
    probabilities = {pos: count / n_simulations for pos, count in sorted(counts.items())}

    expected_position = float(np.mean(finish_positions))
    position_gain_expected = current_position - expected_position
    risk_of_losing_positions = float(np.mean(finish_positions > current_position))

    return PositionPrediction(
        car_id=own.car_id,
        lap=lap,
        source="monte_carlo",
        position_probabilities=probabilities,
        expected_position=expected_position,
        position_gain_expected=position_gain_expected,
        risk_of_losing_positions=risk_of_losing_positions,
        n_simulations=n_simulations,
        note=f"Monte Carlo over {len(opponents)} opponents, {n_simulations} draws.",
    )
