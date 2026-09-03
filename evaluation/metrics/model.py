"""Shared backtesting and evaluation metric definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class StrategyPerformanceMetrics:
    scenario_id: str
    strategy_type: str  # "AI_STRATEGY" or "NAIVE_BASELINE"
    total_race_time_s: float
    final_position: int
    positions_gained: int
    pit_stops_executed: int
    average_lap_time_s: float
    tyre_cliff_hits: int
    false_alert_count: int
    average_decision_latency_ms: float


@dataclass
class ScenarioEvaluationComparison:
    scenario_id: str
    scenario_name: str
    ai_metrics: StrategyPerformanceMetrics
    baseline_metrics: StrategyPerformanceMetrics
    time_delta_s: float  # Negative means AI was faster
    position_delta: int  # Positive means AI finished higher
    ai_outperformed: bool
    summary: str


@dataclass
class EvaluationReport:
    timestamp_iso: str
    scenarios_evaluated: int
    ai_win_count: int
    baseline_win_count: int
    tie_count: int
    total_time_saved_s: float
    comparisons: list[ScenarioEvaluationComparison] = field(default_factory=list)
