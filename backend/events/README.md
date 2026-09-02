# backend/events

**Status: implemented (Phase 8), partially — see `model.py::DETECTOR_STATUS`.**

All 15 event types from the problem statement are declared in
`model.py::EventType`. Six are genuinely detectable today, each edge-
triggered against remembered per-car state so a detector fires exactly
once per transition rather than once per frame while the condition holds:
`SAFETY_CAR`, `VSC` (from raw `RaceTelemetry` flags), `TYRE_CLIFF_APPROACHING`,
`TYRE_DEGRADATION_ACCELERATING` (from `backend/tyre`), `PACE_DROP` (from
`backend/pace`), `FREE_PIT_WINDOW` (from `backend/state`'s baseline
trajectory). The other nine need intelligence layers that don't exist yet
(`OPPONENT_PITTING`/`UNDERCUT_OPPORTUNITY`/`OVERCUT_OPPORTUNITY`/
`TRAFFIC_RELEASE`/`POSITION_THREAT`/`POSITION_OPPORTUNITY` → Phase 14;
`RAIN_INCOMING` → Phase 13; `RACING_LINE_DEGRADATION` → Phase 15;
`STRATEGY_FAILURE` → Phase 9, needs an actual decision to evaluate) —
`DETECTOR_STATUS` states this plainly and a test
(`test_detector_status_covers_every_event_type`) keeps the vocabulary and
the status map from drifting apart.

`EventDetectionEngine.detect(state)` is called after every frame and does
a constant amount of comparison work — no per-packet simulation. Strategy
reassessment on important events is Phase 9's job (not built yet); this
engine only produces the events.
