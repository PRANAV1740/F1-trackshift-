# backend/racing_line

**Status:** implemented (Phase 15).

Track representation plus per-corner telemetry analysis:
- Braking point distance and peak intensity.
- Entry, apex, and exit speeds.
- Line deviation vs reference ideal line on `SyntheticTrack`.
- Estimated corner and total lap time loss.
- Line classification (`IDEAL`, `ATTACKING`, `DEFENSIVE`).
- Corner time loss trend tracking across laps, surfacing `line_degradation_detected`.
- Fires `RACING_LINE_DEGRADATION` event in `backend/events`.

Exercised end-to-end in `tests/test_racing_line.py`.
