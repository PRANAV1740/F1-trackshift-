"""`RacingLineEstimator`: wires `backend/racing_line/model.py` into `RaceState`.

Collects telemetry frames for each car, performs corner racing-line analysis upon lap
completion, updates `RaceState.racing_line_analysis`, and tracks degradation trends
across laps.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from backend.observability.logging import get_logger
from backend.racing_line.model import RacingLineAnalysis, analyze_lap_racing_line
from backend.state.race_state import RaceState
from backend.telemetry.schema import RaceTelemetry
from simulator.generator.track import SyntheticTrack, default_track

log = get_logger("racing_line.estimator")

DEGRADATION_TIME_LOSS_THRESHOLD_S = 0.4


class RacingLineEstimator:
    def __init__(self, track: SyntheticTrack | None = None):
        self._track = track or default_track()
        self._current_lap_frames: dict[str, list[RaceTelemetry]] = defaultdict(list)
        self._analyses: dict[str, list[RacingLineAnalysis]] = defaultdict(list)

    def process_frame(self, frame: RaceTelemetry) -> None:
        """Accumulates a telemetry frame for racing-line corner analysis."""
        if frame.car_id and frame.lap:
            self._current_lap_frames[frame.car_id].append(frame)

    def update(self, state: RaceState) -> Optional[RacingLineAnalysis]:
        """Event-driven update: if a lap completed, run corner analysis and attach to state."""
        car_id = state.car_id
        frames = self._current_lap_frames.get(car_id, [])

        if state.latest_frame is not None:
            # Add latest frame if not already added
            if not frames or frames[-1].source_timestamp != state.latest_frame.source_timestamp:
                frames.append(state.latest_frame)

        # Check if we have completed laps to analyze
        if not state.completed_laps:
            return None

        last_completed_lap = state.completed_laps[-1].lap

        # Check if we already analyzed this completed lap
        car_analyses = self._analyses[car_id]
        if car_analyses and car_analyses[-1].lap == last_completed_lap:
            state.racing_line_analysis = car_analyses[-1]
            return car_analyses[-1]

        # Filter frames for the completed lap
        lap_frames = [f for f in frames if f.lap == last_completed_lap]
        if not lap_frames and frames:
            lap_frames = frames

        analysis = analyze_lap_racing_line(
            car_id=car_id,
            lap=last_completed_lap,
            frames=lap_frames,
            track=self._track,
        )

        # Check trend for line degradation
        if len(car_analyses) >= 2:
            baseline_loss = car_analyses[0].total_time_loss_s
            current_loss = analysis.total_time_loss_s
            if current_loss - baseline_loss >= DEGRADATION_TIME_LOSS_THRESHOLD_S:
                # Re-create analysis with line_degradation_detected = True
                analysis = RacingLineAnalysis(
                    car_id=analysis.car_id,
                    lap=analysis.lap,
                    corner_analyses=analysis.corner_analyses,
                    total_time_loss_s=analysis.total_time_loss_s,
                    overall_classification=analysis.overall_classification,
                    line_degradation_detected=True,
                )

        car_analyses.append(analysis)
        state.racing_line_analysis = analysis

        # Keep frame buffer bounded (retain only frames for current and previous lap)
        self._current_lap_frames[car_id] = [
            f for f in frames if f.lap >= state.current_lap
        ]

        log.info(
            "racing line analysis updated",
            extra={
                "fields": {
                    "car_id": car_id,
                    "lap": last_completed_lap,
                    "total_time_loss_s": analysis.total_time_loss_s,
                    "overall_classification": analysis.overall_classification.value,
                    "line_degradation_detected": analysis.line_degradation_detected,
                }
            },
        )

        return analysis

    def get_latest_analysis(self, car_id: str) -> Optional[RacingLineAnalysis]:
        car_analyses = self._analyses.get(car_id, [])
        return car_analyses[-1] if car_analyses else None
