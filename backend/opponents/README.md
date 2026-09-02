# backend/opponents

**Status:** not yet implemented (Phase 14).

Per-opponent derived state: position, compound, tyre age, pace,
degradation, pit probability, pit window, undercut/overcut threat, gap,
traffic (see problem prompt section 10). Consumes the raw, per-frame
`OpponentState` snapshots on `RaceTelemetry` (backend/telemetry/schema.py)
plus this car's own `backend/tyre` and `backend/pace` outputs, and produces
the richer intelligence view that `backend/events` and `backend/strategy`
react to (e.g. `OPPONENT_PITTING`, `UNDERCUT_OPPORTUNITY`).
