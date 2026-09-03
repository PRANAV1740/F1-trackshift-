"""Per-opponent intelligence summaries and strategic-threat heuristics.

Position/compound/tyre-age/pace/degradation for an opponent are NOT
re-derived here -- they're read straight off that opponent's own
`RaceState` (already computed by Phases 4-6, since every per-car estimator
is keyed by `car_id`). What's genuinely new in this module: pit
probability (reusing Phase 5's own cliff/remaining-life numbers, viewed as
a probability), and undercut/overcut threat classification, which needs
BOTH cars' states plus the gap between them (from `backend/opponents/order.py`).

**Documented heuristic, not a fitted model.** Threat classification below
uses fixed, named thresholds on gap and pit probability -- reasonable and
inspectable, but not calibrated against outcome data (there is no
multi-race dataset to calibrate against in this prototype). Treat `HIGH`/
`MEDIUM`/`LOW` as directional signals for a strategist to weigh, not
calibrated probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from backend.state.race_state import RaceState
from backend.telemetry.schema import PitStatus
from backend.telemetry.schema import TyreCompound

UNDERCUT_DANGER_GAP_S = 3.0
UNDERCUT_WARNING_GAP_S = 6.0
OVERCUT_DANGER_GAP_S = 3.0
OVERCUT_WARNING_GAP_S = 6.0
HIGH_PIT_PROBABILITY = 0.5
MEDIUM_PIT_PROBABILITY = 0.25


class ThreatLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class PitTimingOpportunity(str, Enum):
    UNDERCUT = "UNDERCUT"
    OVERCUT = "OVERCUT"


def pit_probability(state: RaceState) -> Optional[float]:
    """A car's own likelihood of pitting soon, from what Phase 5 already
    computed for it -- cliff probability if available (it already IS a
    probability), else a simple linear function of remaining tyre life."""

    if state.tyre_cliff_probability is not None:
        return state.tyre_cliff_probability
    if state.remaining_tyre_life_laps is not None:
        return max(0.0, min(1.0, 1.0 - state.remaining_tyre_life_laps / 15.0))
    return None


def _threat_from(gap_s: Optional[float], their_pit_probability: Optional[float]) -> ThreatLevel:
    if gap_s is None or their_pit_probability is None:
        return ThreatLevel.NONE
    if gap_s <= UNDERCUT_DANGER_GAP_S and their_pit_probability >= HIGH_PIT_PROBABILITY:
        return ThreatLevel.HIGH
    if gap_s <= UNDERCUT_WARNING_GAP_S and their_pit_probability >= MEDIUM_PIT_PROBABILITY:
        return ThreatLevel.MEDIUM
    return ThreatLevel.LOW


@dataclass
class OpponentSummary:
    car_id: str
    position: Optional[int]
    compound: Optional[TyreCompound]
    tyre_age_laps: Optional[int]
    current_pace_s: Optional[float]
    degradation_rate_s_per_lap: Optional[float]
    pit_probability: Optional[float]
    pit_status: Optional[PitStatus]
    gap_magnitude_s: Optional[float]  # always >= 0; direction is in `is_ahead`
    is_ahead: bool
    undercut_threat: ThreatLevel  # they undercut US (relevant if they're behind)
    overcut_threat: ThreatLevel  # they overcut US (relevant if they're ahead)


def summarize_opponent(own: RaceState, opponent: RaceState, gap_magnitude_s: Optional[float], is_ahead: bool) -> OpponentSummary:
    their_pit_probability = pit_probability(opponent)

    undercut_threat = ThreatLevel.NONE
    overcut_threat = ThreatLevel.NONE
    if not is_ahead:
        # Opponent is behind us -- they threaten an undercut if they're
        # close and likely to pit soon (fresh tyres could jump us).
        undercut_threat = _threat_from(gap_magnitude_s, their_pit_probability)
    else:
        # Opponent is ahead of us -- they threaten an overcut if we're the
        # one under pit pressure and they're close enough that us pitting
        # (and them staying out) could drop us behind them.
        our_pit_probability = pit_probability(own)
        overcut_threat = _threat_from(gap_magnitude_s, our_pit_probability)

    return OpponentSummary(
        car_id=opponent.car_id,
        position=opponent.position,
        compound=opponent.tyre_compound,
        tyre_age_laps=opponent.tyre_age_laps,
        current_pace_s=opponent.current_pace_s,
        degradation_rate_s_per_lap=opponent.degradation_rate_s_per_lap,
        pit_probability=their_pit_probability,
        pit_status=opponent.pit_status,
        gap_magnitude_s=gap_magnitude_s,
        is_ahead=is_ahead,
        undercut_threat=undercut_threat,
        overcut_threat=overcut_threat,
    )


def classify_pit_timing_opportunity(
    summary: OpponentSummary,
    own_pit_probability: Optional[float],
    gap_threshold_s: float = UNDERCUT_DANGER_GAP_S,
    opponent_uncommitted_threshold: float = MEDIUM_PIT_PROBABILITY,
    opponent_committed_threshold: float = HIGH_PIT_PROBABILITY,
) -> Optional[PitTimingOpportunity]:
    """Is pitting now, against THIS specific opponent, a genuine undercut or
    overcut -- as opposed to just a tyre-life-driven stop? Shared by
    `backend/events`' `UNDERCUT_OPPORTUNITY`/`OVERCUT_OPPORTUNITY`
    detectors and `backend/strategy`'s UNDERCUT/OVERCUT relabeling, so the
    two don't duplicate or drift on the threshold logic.

    Only applies to an opponent AHEAD -- that's who an undercut/overcut
    targets (see the module docstring in backend/strategy/engine.py for
    why ATTACK/DEFEND, which target an opponent behind, are out of scope
    here). Returns `None` if the opponent isn't ahead, isn't close, or
    neither signal is clear enough.
    """

    if not summary.is_ahead or summary.gap_magnitude_s is None or summary.gap_magnitude_s > gap_threshold_s:
        return None
    if summary.pit_probability is None:
        return None
    if summary.pit_probability <= opponent_uncommitted_threshold:
        return PitTimingOpportunity.UNDERCUT
    if (
        summary.pit_probability >= opponent_committed_threshold
        and own_pit_probability is not None
        and own_pit_probability <= opponent_uncommitted_threshold
    ):
        return PitTimingOpportunity.OVERCUT
    return None
