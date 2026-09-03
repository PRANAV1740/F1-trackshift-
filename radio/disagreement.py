"""Human/AI disagreement detection engine.

Compares driver-reported radio signals against telemetry-derived intelligence
estimates to highlight discrepancies (e.g. driver reports severe tyre wear when
telemetry shows healthy pace, or driver wants to stay out when tyre cliff is imminent).
Assistive, not a replacement for race engineers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from backend.state.race_state import RaceState
from radio.model import DriverRadioMessage, RadioIntent


class DisagreementType(str, Enum):
    DRIVER_REPORTS_TYRE_ISSUE_BUT_TELEMETRY_HEALTHY = "DRIVER_REPORTS_TYRE_ISSUE_BUT_TELEMETRY_HEALTHY"
    DRIVER_REPORTS_TYRES_FINE_BUT_CLIFF_IMMINENT = "DRIVER_REPORTS_TYRES_FINE_BUT_CLIFF_IMMINENT"
    DRIVER_REQUESTS_PIT_BUT_STRATEGY_RECOMMENDS_STAY_OUT = "DRIVER_REQUESTS_PIT_BUT_STRATEGY_RECOMMENDS_STAY_OUT"
    DRIVER_REPORTS_RAIN_BUT_WEATHER_DRY = "DRIVER_REPORTS_RAIN_BUT_WEATHER_DRY"
    DRIVER_REPORTS_TRAFFIC_BUT_GAP_LARGE = "DRIVER_REPORTS_TRAFFIC_BUT_GAP_LARGE"


@dataclass(frozen=True)
class HumanAIDisagreement:
    car_id: str
    lap: int
    timestamp: datetime
    disagreement_type: DisagreementType
    radio_message: DriverRadioMessage
    telemetry_evidence: dict[str, Any]
    summary: str
    severity: str = "WARNING"


class HumanAIDisagreementDetector:
    """Evaluates conflict between human driver reports and model estimations."""

    def evaluate_disagreement(
        self,
        state: RaceState,
        message: Optional[DriverRadioMessage] = None,
    ) -> list[HumanAIDisagreement]:
        msg = message or state.latest_radio_message
        if msg is None:
            return []

        disagreements: list[HumanAIDisagreement] = []
        now = state.last_updated or datetime.now(timezone.utc)
        intents = msg.detected_intents

        # Check 1: Driver reports tyre issue (graining/overheating/puncture) but degradation is low
        tyre_issue_intents = {RadioIntent.TYRE_GRAINING, RadioIntent.TYRE_OVERHEATING, RadioIntent.TYRE_PUNCTURE}
        if any(i in intents for i in tyre_issue_intents):
            deg = state.estimated_degradation_s
            rate = state.degradation_rate_s_per_lap
            if deg is not None and deg < 0.25 and (rate is None or rate < 0.04):
                disagreements.append(
                    HumanAIDisagreement(
                        car_id=state.car_id,
                        lap=state.current_lap,
                        timestamp=now,
                        disagreement_type=DisagreementType.DRIVER_REPORTS_TYRE_ISSUE_BUT_TELEMETRY_HEALTHY,
                        radio_message=msg,
                        telemetry_evidence={
                            "estimated_degradation_s": deg,
                            "degradation_rate_s_per_lap": rate,
                            "raw_text": msg.raw_text,
                        },
                        summary=f"Driver reported tyre issues ('{msg.raw_text}'), but telemetry shows low degradation ({deg:.2f}s).",
                    )
                )

        # Check 2: Driver reports tyres fine / wants stay out, but cliff probability is high
        if RadioIntent.STRATEGY_STAY_OUT_REQUEST in intents:
            cliff_prob = state.tyre_cliff_probability
            if cliff_prob is not None and cliff_prob >= 0.5:
                disagreements.append(
                    HumanAIDisagreement(
                        car_id=state.car_id,
                        lap=state.current_lap,
                        timestamp=now,
                        disagreement_type=DisagreementType.DRIVER_REPORTS_TYRES_FINE_BUT_CLIFF_IMMINENT,
                        radio_message=msg,
                        telemetry_evidence={
                            "tyre_cliff_probability": cliff_prob,
                            "tyre_age_laps": state.tyre_age_laps,
                            "raw_text": msg.raw_text,
                        },
                        summary=f"Driver wants to stay out ('{msg.raw_text}'), but tyre cliff probability is high ({cliff_prob:.0%}).",
                    )
                )

        # Check 3: Driver requests pit stop, but strategy engine recommends STAY_OUT
        if RadioIntent.STRATEGY_PIT_REQUEST in intents:
            strategy = state.current_strategy
            decision_val = strategy.decision.value if (strategy and hasattr(strategy.decision, "value")) else (strategy.decision if strategy else "")
            if strategy is not None and decision_val in ("STAY_OUT", "EXTEND") and strategy.confidence > 0.6:
                disagreements.append(
                    HumanAIDisagreement(
                        car_id=state.car_id,
                        lap=state.current_lap,
                        timestamp=now,
                        disagreement_type=DisagreementType.DRIVER_REQUESTS_PIT_BUT_STRATEGY_RECOMMENDS_STAY_OUT,
                        radio_message=msg,
                        telemetry_evidence={
                            "strategy_decision": decision_val,
                            "strategy_confidence": strategy.confidence,
                            "raw_text": msg.raw_text,
                        },
                        summary=f"Driver requested pit ('{msg.raw_text}'), but strategy engine recommends {decision_val} ({strategy.confidence:.0%}).",
                    )
                )

        # Check 4: Driver reports rain, but weather indicators show dry
        if RadioIntent.RAIN_REPORTED in intents:
            rain_prob = state.rain_probability
            if rain_prob is not None and rain_prob < 0.15:
                disagreements.append(
                    HumanAIDisagreement(
                        car_id=state.car_id,
                        lap=state.current_lap,
                        timestamp=now,
                        disagreement_type=DisagreementType.DRIVER_REPORTS_RAIN_BUT_WEATHER_DRY,
                        radio_message=msg,
                        telemetry_evidence={
                            "rain_probability": rain_prob,
                            "weather": state.weather,
                            "raw_text": msg.raw_text,
                        },
                        summary=f"Driver reported rain ('{msg.raw_text}'), but telemetry weather sensors read dry ({rain_prob:.0%}).",
                    )
                )

        # Check 5: Driver reports heavy traffic, but gap ahead is clear
        if RadioIntent.TRAFFIC_HEAVY in intents:
            gap_ahead = state.gap_ahead_s
            if gap_ahead is not None and gap_ahead > 3.0:
                disagreements.append(
                    HumanAIDisagreement(
                        car_id=state.car_id,
                        lap=state.current_lap,
                        timestamp=now,
                        disagreement_type=DisagreementType.DRIVER_REPORTS_TRAFFIC_BUT_GAP_LARGE,
                        radio_message=msg,
                        telemetry_evidence={
                            "gap_ahead_s": gap_ahead,
                            "raw_text": msg.raw_text,
                        },
                        summary=f"Driver reported traffic ('{msg.raw_text}'), but gap to car ahead is clear ({gap_ahead:.1f}s).",
                    )
                )

        return disagreements
