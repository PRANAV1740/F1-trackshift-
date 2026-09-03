"""Backtesting & evaluation tests for Phase 20 (`evaluation/backtesting`)."""

from __future__ import annotations

import pytest

from evaluation.backtesting.engine import BacktestEngine
from evaluation.metrics.model import EvaluationReport, ScenarioEvaluationComparison


def test_evaluate_tyre_cliff_scenario_ai_outperforms_baseline():
    engine = BacktestEngine()
    comp = engine.evaluate_scenario("tyre_cliff", seed=42)

    assert isinstance(comp, ScenarioEvaluationComparison)
    assert comp.ai_outperformed is True
    assert comp.time_delta_s < 0.0


def test_evaluate_normal_race_scenario_performance_similar():
    engine = BacktestEngine()
    comp = engine.evaluate_scenario("normal_race", seed=42)

    assert isinstance(comp, ScenarioEvaluationComparison)
    assert abs(comp.time_delta_s) <= 1.0


def test_run_full_evaluation_scenarios():
    engine = BacktestEngine()
    report = engine.run_full_evaluation(seed=42)

    assert isinstance(report, EvaluationReport)
    assert report.scenarios_evaluated == 12
    assert len(report.comparisons) == 12
    assert report.ai_win_count >= 6
    assert report.total_time_saved_s > 0.0
