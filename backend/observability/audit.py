"""Decision Audit Trail module for Phase 25.

Emits structured JSON decision audit records documenting inputs, model versions,
top 3 reasons, invalidation conditions, predicted vs actual outcomes after 5 laps.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from backend.state.race_state import RaceState


@dataclass
class DecisionAuditRecord:
    decision_id: str
    timestamp_iso: str
    car_id: str
    lap: int
    inputs: dict[str, Any]
    model_versions: dict[str, str]
    decision: str
    confidence: float
    top_3_reasons: list[str]
    invalidation_conditions: list[str]
    predicted_outcome: dict[str, Any]
    actual_outcome_lap_plus_5: Optional[dict[str, Any]] = None
    outcome_accuracy_error_s: Optional[float] = None


class DecisionAuditLogger:
    """Records and evaluates strategy decision audit trails."""

    def __init__(self):
        self._audit_records: dict[str, DecisionAuditRecord] = {}
        self._pending_evaluations: list[tuple[int, str]] = []  # (target_lap, decision_id)

    def log_decision(
        self,
        state: RaceState,
        model_versions: Optional[dict[str, str]] = None,
    ) -> DecisionAuditRecord:
        if model_versions is None:
            model_versions = {
                "tyre_model": "1.5.0",
                "pace_model": "1.2.0",
                "strategy_engine": "1.0.0",
                "event_detector": "1.0.0",
            }

        strategy = state.current_strategy
        decision_str = strategy.decision.value if strategy else "STAY_OUT"
        confidence = strategy.confidence if strategy else 0.5
        reasons = (strategy.reasons if strategy else [])[:3]
        invalidation = [
            "Safety Car or VSC deployed ahead of pit window",
            "Rain intensity exceeds 0.20 mm/min",
            "Unscheduled front-wing structural damage",
        ]

        pred_pos = strategy.expected_position if (strategy and strategy.expected_position is not None) else state.position
        pred_delta = (state.position - pred_pos) * 1.5 if pred_pos else 0.0

        record = DecisionAuditRecord(
            decision_id=str(uuid.uuid4()),
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
            car_id=state.car_id,
            lap=state.current_lap,
            inputs={
                "position": state.position,
                "tyre_compound": state.tyre_compound.value if state.tyre_compound else "UNKNOWN",
                "tyre_age_laps": state.tyre_age_laps,
                "estimated_degradation_s": state.estimated_degradation_s,
                "tyre_cliff_probability": state.tyre_cliff_probability,
                "weather": state.weather.value if state.weather else "DRY",
                "gap_ahead_s": state.gap_ahead_s,
                "gap_behind_s": state.gap_behind_s,
            },
            model_versions=model_versions,
            decision=decision_str,
            confidence=confidence,
            top_3_reasons=reasons,
            invalidation_conditions=invalidation,
            predicted_outcome={
                "predicted_position_lap_plus_5": pred_pos,
                "predicted_time_gain_s": pred_delta,
            },
        )

        self._audit_records[record.decision_id] = record
        self._pending_evaluations.append((state.current_lap + 5, record.decision_id))
        return record

    def check_and_evaluate_outcomes(self, current_state: RaceState) -> list[DecisionAuditRecord]:
        evaluated = []
        remaining = []
        for target_lap, dec_id in self._pending_evaluations:
            if current_state.current_lap >= target_lap and dec_id in self._audit_records:
                record = self._audit_records[dec_id]
                pred_pos = record.predicted_outcome.get("predicted_position_lap_plus_5", current_state.position)
                actual_pos = current_state.position
                pos_error = abs(actual_pos - pred_pos)

                record.actual_outcome_lap_plus_5 = {
                    "actual_position": actual_pos,
                    "actual_lap": current_state.current_lap,
                    "actual_gap_ahead_s": current_state.gap_ahead_s,
                }
                record.outcome_accuracy_error_s = float(pos_error * 1.2)
                evaluated.append(record)
            else:
                remaining.append((target_lap, dec_id))
        self._pending_evaluations = remaining
        return evaluated

    def get_history(self, car_id: Optional[str] = None) -> list[DecisionAuditRecord]:
        records = list(self._audit_records.values())
        if car_id:
            records = [r for r in records if r.car_id == car_id]
        return records

    def export_json(self) -> str:
        return json.dumps([asdict(r) for r in self._audit_records.values()], indent=2, default=str)
