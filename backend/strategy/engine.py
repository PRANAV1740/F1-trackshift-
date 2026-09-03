"""The strategy decision engine -- the ONLY module allowed to decide PIT/STAY_OUT.

`decide()` is a pure function: given a `RaceState` and the fitted
estimates available for it, it scores every candidate action against the
objective function in `objective.py` and returns a `StrategyDecision` that
answers every question the problem statement requires: should we pit, when,
which compound, why, what's the confidence, what could invalidate it. Two
questions -- expected position and position gain -- are honestly answered
with a naive placeholder (see `StrategyDecision.position_forecast_is_naive`)
because a real answer needs Phase 11 (position prediction) and Phase 14
(opponent intelligence), neither built yet.

`UNDERCUT`/`OVERCUT`/`ATTACK`/`DEFEND` remain in `StrategyDecisionType` (the
decision vocabulary is declared complete from the start, same pattern as
`backend/events`), but `decide()` never selects them yet -- they require
opponent-relative reasoning that doesn't exist until Phase 14. Extending
`decide()` to consider them is Phase 14's job, not a rewrite of this one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from backend.pace.estimator import PaceIntelligenceEstimator
from backend.state.baseline import estimate_fuel_burn_rate
from backend.state.race_state import RaceState
from backend.strategy import objective
from backend.telemetry.schema import TyreCompound
from backend.tyre.estimator import TyreDegradationEstimator


class StrategyDecisionType(str, Enum):
    PIT = "PIT"
    STAY_OUT = "STAY_OUT"
    PIT_NEXT_LAP = "PIT_NEXT_LAP"
    EXTEND = "EXTEND"
    UNDERCUT = "UNDERCUT"
    OVERCUT = "OVERCUT"
    ATTACK = "ATTACK"
    DEFEND = "DEFEND"


@dataclass
class StrategyConfig:
    race_total_laps: int = 50
    base_pit_loss_s: float = 22.0
    vsc_pit_loss_multiplier: float = 0.45
    sc_pit_loss_multiplier: float = 0.30
    extend_remaining_life_threshold_laps: int = 5
    pit_next_lap_cliff_probability_threshold: float = 0.6
    candidate_compounds: tuple[TyreCompound, ...] = (TyreCompound.SOFT, TyreCompound.MEDIUM, TyreCompound.HARD)
    confidence_margin_scale_s: float = 8.0


POSITION_FORECAST_NAIVE_NOTE = (
    "expected_position/position_gain are a naive carry-forward (assumes clean "
    "execution, no on-track battles) -- a modeled forecast needs Phase 11 "
    "(position prediction) and Phase 14 (opponent intelligence), neither "
    "implemented yet"
)


@dataclass
class StrategyDecision:
    car_id: str
    lap: int
    decision: StrategyDecisionType
    compound: Optional[TyreCompound]
    window: Optional[tuple[int, int]]
    confidence: float
    expected_position: Optional[int]
    position_gain: Optional[int]
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    candidate_scores: dict[str, float] = field(default_factory=dict)
    position_forecast_is_naive: bool = True

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "compound": self.compound.value if self.compound else None,
            "window": list(self.window) if self.window else None,
            "confidence": round(self.confidence, 3),
            "expected_position": self.expected_position,
            "position_gain": self.position_gain,
            "reasons": self.reasons,
            "risks": self.risks,
            "invalidation_conditions": self.invalidation_conditions,
        }


def decide(
    state: RaceState,
    tyre_estimator: TyreDegradationEstimator,
    pace_estimator: Optional[PaceIntelligenceEstimator] = None,
    config: StrategyConfig = StrategyConfig(),
) -> StrategyDecision:
    remaining_laps = max(config.race_total_laps - state.current_lap, 0)
    fuel_burn_rate = estimate_fuel_burn_rate(state)
    current_fuel = state.fuel_load_kg or 0.0
    current_age = state.tyre_age_laps or 0

    current_estimate = tyre_estimator.get_estimate(state.car_id, state.tyre_compound) if state.tyre_compound else None
    pace_estimate = pace_estimator.get_estimate(state.car_id) if pace_estimator else None
    base_pace = current_estimate.base_pace_s if current_estimate else (
        pace_estimate.expected_clean_pace_s if pace_estimate else None
    )

    if remaining_laps <= 0 or base_pace is None:
        return _insufficient_data_decision(state, remaining_laps)

    stay_out = objective.score_stay_out(
        current_estimate, base_pace, state.current_lap, current_age, current_fuel, fuel_burn_rate, remaining_laps
    )

    is_vsc_or_sc = state.safety_car or state.vsc
    pit_loss = config.base_pit_loss_s * (
        config.sc_pit_loss_multiplier if state.safety_car else (config.vsc_pit_loss_multiplier if state.vsc else 1.0)
    )

    pit_candidates = [
        objective.score_pit(
            compound,
            tyre_estimator.get_estimate(state.car_id, compound),
            current_estimate,
            base_pace,
            state.current_lap,
            current_fuel,
            fuel_burn_rate,
            remaining_laps,
            pit_loss,
        )
        for compound in config.candidate_compounds
    ]

    all_candidates = [stay_out] + pit_candidates
    ranked = sorted(all_candidates, key=lambda c: c.total_score_s)
    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None

    margin_s = (runner_up.total_score_s - best.total_score_s) if runner_up else config.confidence_margin_scale_s
    confidence = 0.5 + min(margin_s / config.confidence_margin_scale_s, 0.4)
    if best.used_fallback_curve:
        confidence *= 0.8
    if best.degradation_estimate is not None and best.degradation_estimate.n_observations < 8:
        confidence *= 0.9
    confidence = max(0.05, min(confidence, 0.95))

    reasons: list[str] = [
        f"Best candidate '{best.label}' projects {best.total_score_s:.2f}s over the comparison horizon "
        f"vs {runner_up.total_score_s:.2f}s for '{runner_up.label}'." if runner_up else f"Only candidate: '{best.label}'."
    ]
    risks: list[str] = []
    invalidations: list[str] = []

    if best.used_fallback_curve:
        risks.append(f"No fitted degradation curve for {best.compound.value if best.compound else 'this compound'} yet this session; used an assumed prior.")
    if best.degradation_estimate is not None and best.degradation_estimate.n_observations < 8:
        risks.append(f"Degradation estimate based on only {best.degradation_estimate.n_observations} laps.")
    risks.append(POSITION_FORECAST_NAIVE_NOTE)

    if best.pits:
        urgent = is_vsc_or_sc or (state.tyre_cliff_probability or 0.0) >= config.pit_next_lap_cliff_probability_threshold
        decision_type = StrategyDecisionType.PIT_NEXT_LAP if urgent else StrategyDecisionType.PIT
        compound = best.compound
        if is_vsc_or_sc:
            reasons.append(f"{'Safety car' if state.safety_car else 'VSC'} active -- pit loss reduced to {pit_loss:.1f}s.")
            invalidations.append("Invalidated if the safety car / VSC period ends before this car reaches the pit entry.")
        if state.tyre_cliff_probability is not None and state.tyre_cliff_probability >= config.pit_next_lap_cliff_probability_threshold:
            reasons.append(f"Tyre cliff probability {state.tyre_cliff_probability:.0%} within the near-term window.")
        window = (state.current_lap + 1, state.current_lap + 1) if urgent else (
            state.baseline_trajectory.recommended_pit_window if state.baseline_trajectory and state.baseline_trajectory.recommended_pit_window
            else (state.current_lap + 1, min(state.current_lap + 3, config.race_total_laps))
        )
        invalidations.append("Invalidated if the degradation trend reverses (e.g. cooler track, lower fuel-burn-off benefit than assumed) before pit entry.")
    else:
        compound = None
        window = None
        remaining_life = state.remaining_tyre_life_laps
        if remaining_life is not None and remaining_life >= config.extend_remaining_life_threshold_laps:
            decision_type = StrategyDecisionType.EXTEND
            reasons.append(f"Estimated {remaining_life} laps of remaining competitive tyre life.")
        else:
            decision_type = StrategyDecisionType.STAY_OUT
        invalidations.append("Invalidated if degradation rate or cliff probability increases materially next lap.")

    return StrategyDecision(
        car_id=state.car_id,
        lap=state.current_lap,
        decision=decision_type,
        compound=compound,
        window=window,
        confidence=confidence,
        expected_position=state.position,
        position_gain=0,
        reasons=reasons,
        risks=risks,
        invalidation_conditions=invalidations,
        candidate_scores={c.label: round(c.total_score_s, 3) for c in all_candidates},
    )


def _insufficient_data_decision(state: RaceState, remaining_laps: int) -> StrategyDecision:
    reason = "Race distance exhausted." if remaining_laps <= 0 else "Not enough data yet to fit a pace/degradation model."
    return StrategyDecision(
        car_id=state.car_id,
        lap=state.current_lap,
        decision=StrategyDecisionType.STAY_OUT,
        compound=None,
        window=None,
        confidence=0.1,
        expected_position=state.position,
        position_gain=0,
        reasons=[reason],
        risks=["Decision made with insufficient model data; defaulting to STAY_OUT.", POSITION_FORECAST_NAIVE_NOTE],
        invalidation_conditions=["Invalidated as soon as enough laps exist to fit a degradation/pace model."],
        candidate_scores={},
    )
