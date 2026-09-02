"""Ground-truth pace-effect models used ONLY by the simulator.

These functions generate synthetic telemetry with a *known* answer, so
that Phase 5/6 estimators (backend/tyre, backend/pace) can be validated
against a known ground truth under noise. That validation only works if
the estimators never import from this module -- they must recover these
effects purely from observed telemetry (see docs/VALIDATION.md and
docs/MODELS.md once populated). Only test/evaluation code is allowed to
import this module to check estimator output against it.

All constants are illustrative and documented as assumptions; none are
sourced from real car/tyre data (engineering rule 8).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.telemetry.schema import TyreCompound

# seconds of lap-time penalty per kg of fuel carried -- a commonly cited
# rule-of-thumb order of magnitude, not a measured constant.
FUEL_EFFECT_S_PER_KG = 0.033

# track evolution: laps get faster early in a run as rubber goes down,
# saturating after `EVOLUTION_SATURATION_LAP`.
EVOLUTION_MAX_GAIN_S = 0.8
EVOLUTION_SATURATION_LAP = 15


@dataclass(frozen=True)
class CompoundDegradationModel:
    """Linear degradation up to a cliff lap, then accelerating (quadratic) beyond it."""

    linear_rate_s_per_lap: float
    cliff_lap: int
    cliff_coeff_s_per_lap2: float
    thermal_warmup_laps: int = 2
    warmup_penalty_s: float = 0.35

    def pace_penalty_s(self, tyre_age_laps: int) -> float:
        if tyre_age_laps <= 0:
            return 0.0
        linear = self.linear_rate_s_per_lap * tyre_age_laps
        cliff_excess = max(0, tyre_age_laps - self.cliff_lap)
        cliff = self.cliff_coeff_s_per_lap2 * (cliff_excess**2)
        warmup = 0.0
        if tyre_age_laps < self.thermal_warmup_laps:
            warmup = self.warmup_penalty_s * (1 - tyre_age_laps / self.thermal_warmup_laps)
        return linear + cliff + warmup

    def degradation_rate_s_per_lap(self, tyre_age_laps: int) -> float:
        """d(penalty)/d(age), i.e. the instantaneous degradation rate."""

        cliff_excess = max(0, tyre_age_laps - self.cliff_lap)
        return self.linear_rate_s_per_lap + 2 * self.cliff_coeff_s_per_lap2 * cliff_excess


COMPOUND_MODELS: dict[TyreCompound, CompoundDegradationModel] = {
    TyreCompound.SOFT: CompoundDegradationModel(0.045, cliff_lap=12, cliff_coeff_s_per_lap2=0.018),
    TyreCompound.MEDIUM: CompoundDegradationModel(0.028, cliff_lap=22, cliff_coeff_s_per_lap2=0.010),
    TyreCompound.HARD: CompoundDegradationModel(0.018, cliff_lap=35, cliff_coeff_s_per_lap2=0.006),
    TyreCompound.INTERMEDIATE: CompoundDegradationModel(0.020, cliff_lap=25, cliff_coeff_s_per_lap2=0.008),
    TyreCompound.WET: CompoundDegradationModel(0.015, cliff_lap=30, cliff_coeff_s_per_lap2=0.006),
}


def fuel_effect_s(fuel_load_kg: float) -> float:
    return FUEL_EFFECT_S_PER_KG * max(fuel_load_kg, 0.0)


def track_evolution_gain_s(lap: int) -> float:
    """Negative contribution (track gets faster) that saturates after a few laps."""

    progress = min(lap, EVOLUTION_SATURATION_LAP) / EVOLUTION_SATURATION_LAP
    return -EVOLUTION_MAX_GAIN_S * progress
