"""Racing line intelligence data structures and per-corner analysis.

Analyzes telemetry frames over a lap against the synthetic track model
(`simulator/generator/track.py`) to compute per-corner braking points, entry/apex/exit
speeds, line deviations, estimated time loss per corner, and line classifications
(IDEAL, ATTACKING, DEFENSIVE).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from backend.telemetry.schema import RaceTelemetry
from simulator.generator.track import SyntheticTrack, default_track


class LineClassification(str, Enum):
    IDEAL = "IDEAL"
    ATTACKING = "ATTACKING"
    DEFENSIVE = "DEFENSIVE"


@dataclass(frozen=True)
class CornerAnalysis:
    corner_number: int
    corner_name: str
    braking_point_m: Optional[float]
    braking_intensity: float
    entry_speed_kph: float
    apex_speed_kph: float
    exit_speed_kph: float
    line_deviation_m: float
    time_loss_s: float
    classification: LineClassification


@dataclass(frozen=True)
class RacingLineAnalysis:
    car_id: str
    lap: int
    corner_analyses: list[CornerAnalysis] = field(default_factory=list)
    total_time_loss_s: float = 0.0
    overall_classification: LineClassification = LineClassification.IDEAL
    line_degradation_detected: bool = False


def analyze_lap_racing_line(
    car_id: str,
    lap: int,
    frames: list[RaceTelemetry],
    track: SyntheticTrack | None = None,
) -> RacingLineAnalysis:
    """Computes per-corner racing-line analysis for a single completed lap.

    Maps frames to distance along lap by integrating speed over time, evaluates
    braking initiation, corner speeds, line deviation, and time loss against
    reference corner parameters on `SyntheticTrack`.
    """

    if track is None:
        track = default_track()

    if not frames:
        return RacingLineAnalysis(car_id=car_id, lap=lap)

    # Calculate cumulative distance along lap for each frame
    distances: list[float] = [0.0]
    current_dist = 0.0
    for i in range(1, len(frames)):
        prev_f = frames[i - 1]
        curr_f = frames[i]
        dt = (curr_f.source_timestamp - prev_f.source_timestamp).total_seconds()
        if dt < 0 or dt > 2.0:
            dt = 0.2  # default 5Hz step fallback
        avg_speed = ((curr_f.speed_kph or 0.0) + (prev_f.speed_kph or 0.0)) / 2.0
        ds = (avg_speed / 3.6) * dt
        current_dist += ds
        distances.append(current_dist)

    corner_analyses: list[CornerAnalysis] = []
    total_time_loss = 0.0
    classifications_count: dict[LineClassification, int] = {
        LineClassification.IDEAL: 0,
        LineClassification.ATTACKING: 0,
        LineClassification.DEFENSIVE: 0,
    }

    for corner in track.corners:
        half = corner.arc_length_m / 2.0
        entry_dist = corner.apex_distance_m - half
        exit_dist = corner.apex_distance_m + half
        search_min = entry_dist - 60.0
        search_max = exit_dist + 40.0

        # Filter frames in proximity to this corner
        corner_frame_indices = [
            idx for idx, d in enumerate(distances) if search_min <= d <= search_max
        ]

        if not corner_frame_indices:
            # Fallback if telemetry gap
            continue

        c_frames = [frames[i] for i in corner_frame_indices]
        c_dists = [distances[i] for i in corner_frame_indices]

        # Apex speed: min speed within the corner arc
        apex_candidates = [
            (f.speed_kph, d)
            for f, d in zip(c_frames, c_dists)
            if f.speed_kph is not None and (entry_dist - 10 <= d <= exit_dist + 10)
        ]
        if apex_candidates:
            apex_speed, apex_at_d = min(apex_candidates, key=lambda x: x[0])
        else:
            apex_speed = corner.apex_speed_kph
            apex_at_d = corner.apex_distance_m

        # Entry speed: frame nearest entry_dist
        entry_frame = min(zip(c_frames, c_dists), key=lambda x: abs(x[1] - entry_dist))
        entry_speed = entry_frame[0].speed_kph if entry_frame[0].speed_kph is not None else corner.apex_speed_kph + 20.0

        # Exit speed: frame nearest exit_dist
        exit_frame = min(zip(c_frames, c_dists), key=lambda x: abs(x[1] - exit_dist))
        exit_speed = exit_frame[0].speed_kph if exit_frame[0].speed_kph is not None else corner.apex_speed_kph + 30.0

        # Braking point & intensity
        braking_frames = [
            (f, d)
            for f, d in zip(c_frames, c_dists)
            if d <= apex_at_d
            and (
                (f.brake_pct is not None and f.brake_pct > 5.0)
                or (f.longitudinal_acceleration_g is not None and f.longitudinal_acceleration_g < -0.15)
            )
        ]
        if braking_frames:
            braking_point_m = braking_frames[0][1]
            braking_intensity = max((f.brake_pct or 0.0) for f, _ in braking_frames)
        else:
            braking_point_m = None
            braking_intensity = 0.0

        # Line deviation estimation
        # Compares actual lateral accel (or speed delta) against theoretical apex speed
        speed_diff = max(0.0, corner.apex_speed_kph - apex_speed)
        line_dev_m = round(min(2.5, speed_diff * 0.08), 3)

        # Time loss estimation: difference in travel time through corner arc
        ref_v_ms = corner.apex_speed_kph / 3.6
        act_v_ms = max(5.0, apex_speed) / 3.6
        if act_v_ms < ref_v_ms:
            corner_time_loss = (1.0 / act_v_ms - 1.0 / ref_v_ms) * corner.arc_length_m
            corner_time_loss = max(0.0, min(1.5, corner_time_loss))
        else:
            corner_time_loss = 0.0

        total_time_loss += corner_time_loss

        # Classification
        # Attacking: late braking (within 20m of apex entry), high entry speed, lower exit speed
        # Defensive: early braking (>50m before entry), low entry speed, tight inner line
        expected_braking_dist = corner.apex_distance_m - half - 40.0
        if braking_point_m is not None and braking_point_m > expected_braking_dist + 15.0 and entry_speed > corner.apex_speed_kph + 25.0:
            classification = LineClassification.ATTACKING
        elif braking_point_m is not None and braking_point_m < expected_braking_dist - 20.0 and entry_speed < corner.apex_speed_kph + 15.0:
            classification = LineClassification.DEFENSIVE
        else:
            classification = LineClassification.IDEAL

        classifications_count[classification] += 1

        corner_analyses.append(
            CornerAnalysis(
                corner_number=corner.number,
                corner_name=corner.name,
                braking_point_m=round(braking_point_m, 1) if braking_point_m is not None else None,
                braking_intensity=round(braking_intensity, 1),
                entry_speed_kph=round(entry_speed, 1),
                apex_speed_kph=round(apex_speed, 1),
                exit_speed_kph=round(exit_speed, 1),
                line_deviation_m=line_dev_m,
                time_loss_s=round(corner_time_loss, 3),
                classification=classification,
            )
        )

    # Dominant overall classification
    dominant = max(classifications_count.items(), key=lambda item: item[1])[0]

    return RacingLineAnalysis(
        car_id=car_id,
        lap=lap,
        corner_analyses=corner_analyses,
        total_time_loss_s=round(total_time_loss, 3),
        overall_classification=dominant,
        line_degradation_detected=total_time_loss > 0.4,
    )
