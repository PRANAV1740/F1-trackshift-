"""A deterministic, fully synthetic track layout.

No real circuit geometry is used or claimed anywhere in this project (see
engineering rule 8). This track exists purely so the simulator has
something physically coherent to generate a speed profile against --
distances, corner speeds, and corner order are hand-authored constants,
not derived from or resembling any real venue.

Geometry itself is not seeded/randomized: it is a fixed reference layout,
named "Synthetic Circuit". Only the *telemetry sampled along it* (noise,
timing) is seeded -- see simulator/generator/core.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Corner:
    number: int
    apex_distance_m: float
    apex_speed_kph: float
    arc_length_m: float
    direction: int  # +1 = right-hand, -1 = left-hand
    name: str = ""


@dataclass(frozen=True)
class SyntheticTrack:
    name: str
    length_m: float
    corners: tuple[Corner, ...]

    def corner_at(self, distance_m: float) -> Corner | None:
        """The corner whose arc contains this distance-along-lap, if any."""

        d = distance_m % self.length_m
        for corner in self.corners:
            half = corner.arc_length_m / 2.0
            lo, hi = corner.apex_distance_m - half, corner.apex_distance_m + half
            if lo <= d <= hi:
                return corner
        return None


def default_track() -> SyntheticTrack:
    """A fixed ~5.3km, 14-corner synthetic layout used by every scenario."""

    corners = (
        Corner(1, 350, 90, 120, +1, "Turn 1"),
        Corner(2, 900, 230, 90, -1, "Turn 2"),
        Corner(3, 1400, 70, 100, +1, "Turn 3 (hairpin)"),
        Corner(4, 1750, 180, 80, -1, "Turn 4"),
        Corner(5, 2200, 120, 90, +1, "Turn 5"),
        Corner(6, 2450, 200, 80, -1, "Turn 6"),
        Corner(7, 3000, 60, 110, +1, "Turn 7 (hairpin)"),
        Corner(8, 3300, 160, 80, -1, "Turn 8"),
        Corner(9, 3650, 240, 90, +1, "Turn 9"),
        Corner(10, 4000, 90, 100, -1, "Turn 10"),
        Corner(11, 4300, 150, 80, +1, "Turn 11"),
        Corner(12, 4600, 210, 90, -1, "Turn 12"),
        Corner(13, 4900, 100, 90, +1, "Turn 13"),
        Corner(14, 5150, 190, 80, -1, "Turn 14"),
    )
    return SyntheticTrack(name="Synthetic Circuit", length_m=5303.0, corners=corners)
