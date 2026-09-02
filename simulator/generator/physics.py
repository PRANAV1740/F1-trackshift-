"""A lightweight, point-mass speed-profile model.

This is deliberately NOT a full vehicle-dynamics simulation. It is the
standard simplified "double-pass" lap simulation used by introductory
laptime-simulation tools: a backward braking pass constrains speed
approaching each corner, a forward traction/power pass constrains speed
leaving each corner, and the result at each point on track is the minimum
of the two plus the corner's own apex-speed limit. All physical constants
below (mass, power, braking/traction limits) are illustrative round
numbers, not sourced from or claiming to match any real car -- see
engineering rule 8.

Two passes around the (circular) lap are run so constraints propagate
across the start/finish line; that's sufficient to converge on a synthetic
14-corner layout this size.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from simulator.generator.track import SyntheticTrack

# Illustrative constants -- not derived from real car data.
CAR_MASS_KG = 800.0
POWER_W = 750_000.0  # combined ICE + ERS, order-of-magnitude only
TRACTION_LIMIT_MS2 = 11.0  # ~1.12g, traction-limited accel out of a corner
BRAKE_DECEL_MS2 = 45.0  # ~4.6g, roughly constant-deceleration braking
STEP_M = 5.0


def kph_to_ms(kph: float) -> float:
    return kph / 3.6


def ms_to_kph(ms: float) -> float:
    return ms * 3.6


def power_limited_accel_ms2(speed_ms: float) -> float:
    """Traction-limited at low speed, power-limited at high speed."""

    if speed_ms < 1.0:
        return TRACTION_LIMIT_MS2
    return min(TRACTION_LIMIT_MS2, POWER_W / (CAR_MASS_KG * speed_ms))


@dataclass
class SpeedProfile:
    """Precomputed speed-vs-distance for one lap of a track, at a given fuel load.

    `speeds_ms[i]` is the speed at `positions_m[i] = i * STEP_M`.
    """

    track: SyntheticTrack
    positions_m: list[float]
    speeds_ms: list[float]

    def speed_kph_at(self, distance_m: float) -> float:
        d = distance_m % self.track.length_m
        idx = bisect.bisect_left(self.positions_m, d)
        if idx == 0:
            return ms_to_kph(self.speeds_ms[0])
        if idx >= len(self.positions_m):
            return ms_to_kph(self.speeds_ms[-1])
        d0, d1 = self.positions_m[idx - 1], self.positions_m[idx]
        v0, v1 = self.speeds_ms[idx - 1], self.speeds_ms[idx]
        frac = (d - d0) / (d1 - d0) if d1 > d0 else 0.0
        return ms_to_kph(v0 + frac * (v1 - v0))

    def lap_time_s(self) -> float:
        """Trapezoidal integration of dt = ds / v over the lap."""

        total = 0.0
        n = len(self.positions_m)
        for i in range(1, n):
            ds = self.positions_m[i] - self.positions_m[i - 1]
            v_avg = max((self.speeds_ms[i] + self.speeds_ms[i - 1]) / 2.0, 0.1)
            total += ds / v_avg
        # closing segment back to start/finish
        ds = self.track.length_m - self.positions_m[-1]
        if ds > 0:
            v_avg = max(self.speeds_ms[-1], 0.1)
            total += ds / v_avg
        return total


def build_speed_profile(track: SyntheticTrack, v_max_kph: float = 330.0) -> SpeedProfile:
    n = max(int(track.length_m // STEP_M), 2)
    positions = [i * STEP_M for i in range(n)]

    v_max_ms = kph_to_ms(v_max_kph)
    limit = [v_max_ms] * n

    # Corner apex-speed constraint, applied across each corner's arc.
    for corner in track.corners:
        apex_ms = kph_to_ms(corner.apex_speed_kph)
        half_steps = max(int((corner.arc_length_m / 2.0) // STEP_M), 1)
        center_idx = int(corner.apex_distance_m // STEP_M) % n
        for offset in range(-half_steps, half_steps + 1):
            idx = (center_idx + offset) % n
            limit[idx] = min(limit[idx], apex_ms)

    # Backward braking pass (two laps around, to converge across start/finish).
    for _ in range(2):
        for i in range(n - 1, -1, -1):
            nxt = limit[(i + 1) % n]
            max_allowed = math.sqrt(max(nxt * nxt + 2 * BRAKE_DECEL_MS2 * STEP_M, 0.0))
            limit[i] = min(limit[i], max_allowed)

    # Forward traction/power pass (two laps around).
    speeds = list(limit)
    for _ in range(2):
        for i in range(n):
            prev = speeds[i - 1]
            a = power_limited_accel_ms2(prev)
            max_allowed = math.sqrt(max(prev * prev + 2 * a * STEP_M, 0.0))
            speeds[i] = min(speeds[i], max_allowed, limit[i])

    return SpeedProfile(track=track, positions_m=positions, speeds_ms=speeds)
