"""Latency benchmarking and engineering suite.

Instruments end-to-end telemetry and decision pipeline execution down to per-stage timings:
  * normalization
  * state estimation
  * tyre degradation estimation
  * pace intelligence
  * racing line intelligence
  * opponent intelligence
  * position prediction
  * strategy engine decision
  * event detection

Enforces the target of <2.0s decision latency and hard ceiling of <5.0s under heavy tick rates.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from backend.adapters.simulator_adapter import SimulatorAdapter
from backend.events.detector import EventDetectionEngine
from backend.normalization.stages import default_pipeline
from backend.opponents.estimator import OpponentIntelligenceEstimator
from backend.opponents.order import RaceOrderTracker
from backend.pace.estimator import PaceIntelligenceEstimator
from backend.prediction.estimator import PositionPredictionEstimator
from backend.racing_line.estimator import RacingLineEstimator
from backend.state.estimator import RaceStateEstimator
from backend.strategy.engine import StrategyConfig, decide
from backend.tyre.estimator import TyreDegradationEstimator
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig


@dataclass
class LatencyReport:
    timestamp_iso: str
    total_frames_processed: int
    total_duration_ms: float
    mean_frame_latency_ms: float
    p95_frame_latency_ms: float
    p99_frame_latency_ms: float
    max_frame_latency_ms: float
    mean_decision_latency_ms: float
    max_decision_latency_ms: float
    stage_breakdown_ms: dict[str, float] = field(default_factory=dict)
    target_met: bool = True  # mean decision latency < 2000ms
    hard_ceiling_met: bool = True  # max decision latency < 5000ms


class LatencyBenchmark:
    """End-to-end pipeline benchmark suite."""

    def run_benchmark(self, num_cars: int = 2, laps: int = 10, tick_hz: float = 10.0) -> LatencyReport:
        pipeline = default_pipeline()
        race_state_estimator = RaceStateEstimator()
        tyre_estimator = TyreDegradationEstimator()
        pace_estimator = PaceIntelligenceEstimator()
        racing_line_estimator = RacingLineEstimator()
        opponent_estimator = OpponentIntelligenceEstimator()
        prediction_estimator = PositionPredictionEstimator()
        event_engine = EventDetectionEngine()

        stage_times: dict[str, float] = {
            "normalization": 0.0,
            "state_estimation": 0.0,
            "tyre_degradation": 0.0,
            "pace_intelligence": 0.0,
            "racing_line": 0.0,
            "opponent_intelligence": 0.0,
            "position_prediction": 0.0,
            "strategy_decision": 0.0,
            "event_detection": 0.0,
        }

        frame_latencies: list[float] = []
        decision_latencies: list[float] = []

        all_frames = []
        for i in range(num_cars):
            car_id = str(44 + i)
            cfg = GeneratorConfig(car_id=car_id, laps=laps, tick_hz=tick_hz, noise=NoiseConfig.clean())
            gen = TelemetryGenerator(cfg, seed=100 + i)
            all_frames.extend(list(gen.frames()))

        all_frames.sort(key=lambda f: f.source_timestamp)

        for frame in all_frames:
            t_frame_start = time.perf_counter()

            # Normalization stage
            t0 = time.perf_counter()
            racing_line_estimator.process_frame(frame)
            res = pipeline.process(frame)
            stage_times["normalization"] += (time.perf_counter() - t0) * 1000.0

            # State Estimation stage
            t0 = time.perf_counter()
            state = race_state_estimator.update(res)
            stage_times["state_estimation"] += (time.perf_counter() - t0) * 1000.0

            if state is not None:
                # Tyre stage
                t0 = time.perf_counter()
                tyre_estimator.update(state)
                stage_times["tyre_degradation"] += (time.perf_counter() - t0) * 1000.0

                # Pace stage
                t0 = time.perf_counter()
                pace_estimator.update(state)
                stage_times["pace_intelligence"] += (time.perf_counter() - t0) * 1000.0

                # Racing line stage
                t0 = time.perf_counter()
                racing_line_estimator.update(state)
                stage_times["racing_line"] += (time.perf_counter() - t0) * 1000.0

                # Opponent intelligence stage
                t0 = time.perf_counter()
                opponent_estimator.update_all(race_state_estimator)
                stage_times["opponent_intelligence"] += (time.perf_counter() - t0) * 1000.0

                # Position prediction stage
                t0 = time.perf_counter()
                prediction_estimator.update(state)
                stage_times["position_prediction"] += (time.perf_counter() - t0) * 1000.0

                # Strategy Decision stage
                t0 = time.perf_counter()
                state.current_strategy = decide(state, tyre_estimator, pace_estimator, StrategyConfig())
                dec_time = (time.perf_counter() - t0) * 1000.0
                stage_times["strategy_decision"] += dec_time
                decision_latencies.append(dec_time)

                # Event Detection stage
                t0 = time.perf_counter()
                event_engine.detect(state)
                stage_times["event_detection"] += (time.perf_counter() - t0) * 1000.0

            frame_latencies.append((time.perf_counter() - t_frame_start) * 1000.0)

        frame_latencies.sort()
        decision_latencies.sort()
        n = len(frame_latencies)

        mean_frame = sum(frame_latencies) / max(n, 1)
        p95_frame = frame_latencies[int(n * 0.95)] if n > 0 else 0.0
        p99_frame = frame_latencies[int(n * 0.99)] if n > 0 else 0.0
        max_frame = frame_latencies[-1] if n > 0 else 0.0

        mean_dec = sum(decision_latencies) / max(len(decision_latencies), 1)
        max_dec = decision_latencies[-1] if decision_latencies else 0.0

        return LatencyReport(
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
            total_frames_processed=n,
            total_duration_ms=sum(frame_latencies),
            mean_frame_latency_ms=mean_frame,
            p95_frame_latency_ms=p95_frame,
            p99_frame_latency_ms=p99_frame,
            max_frame_latency_ms=max_frame,
            mean_decision_latency_ms=mean_dec,
            max_decision_latency_ms=max_dec,
            stage_breakdown_ms=stage_times,
            target_met=mean_dec < 2000.0,
            hard_ceiling_met=max_dec < 5000.0,
        )
