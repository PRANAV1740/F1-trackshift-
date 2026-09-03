"""Latency engineering & benchmark tests for Phase 21 (`evaluation/latency`)."""

from __future__ import annotations

import pytest

from evaluation.latency.benchmark import LatencyBenchmark, LatencyReport


def test_latency_benchmark_meets_performance_targets():
    benchmark = LatencyBenchmark()
    report = benchmark.run_benchmark(num_cars=2, laps=5, tick_hz=5.0)

    assert isinstance(report, LatencyReport)
    assert report.total_frames_processed > 0
    assert report.target_met is True  # mean decision latency < 2000ms
    assert report.hard_ceiling_met is True  # max decision latency < 5000ms
    assert report.mean_frame_latency_ms < 50.0  # < 50ms per tick processing time

    stage_keys = [
        "normalization",
        "state_estimation",
        "tyre_degradation",
        "pace_intelligence",
        "racing_line",
        "opponent_intelligence",
        "position_prediction",
        "strategy_decision",
        "event_detection",
    ]
    for key in stage_keys:
        assert key in report.stage_breakdown_ms
        assert report.stage_breakdown_ms[key] >= 0.0
