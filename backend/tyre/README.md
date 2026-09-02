# backend/tyre

**Status:** not yet implemented (Phase 5). This is the official TrackShift
2026 problem statement.

Decomposes observed lap time into base pace + fuel effect + tyre
degradation + track evolution + traffic + driver variation + weather +
other, and estimates the tyre component specifically -- current
degradation, degradation rate, degradation acceleration, tyre age, thermal
state, remaining competitive life, cliff probability, and uncertainty (see
problem prompt section 7). Must NOT collapse to `lap_time_delta ==
degradation`; the separation from confounds is the point of the exercise.

Pairs with `models/tyre_model` for any fitted (as opposed to purely
physics/statistical) component, and `models/uncertainty` for the
uncertainty estimates.
