# backend/events

**Status: implemented (Phase 8), partially — see `model.py::DETECTOR_STATUS`.**

All 15 event types from the problem statement are declared in
`model.py::EventType`. Thirteen are now genuinely detectable, each edge-
triggered against remembered per-car state so a detector fires exactly
once per transition rather than once per frame while the condition holds:
`SAFETY_CAR`, `VSC` (from raw `RaceTelemetry` flags), `TYRE_CLIFF_APPROACHING`,
`TYRE_DEGRADATION_ACCELERATING` (from `backend/tyre`), `PACE_DROP` (from
`backend/pace`), `FREE_PIT_WINDOW` (from `backend/state`'s baseline
trajectory), `RAIN_INCOMING` (from `backend/weather`'s rain-probability
trend, Phase 13), and six opponent-aware detectors added in Phase 14 —
`OPPONENT_PITTING`, `UNDERCUT_OPPORTUNITY`, `OVERCUT_OPPORTUNITY`,
`POSITION_THREAT`, `POSITION_OPPORTUNITY`, `TRAFFIC_RELEASE` — all from
`backend/opponents`' per-car `OpponentSummary`, per-opponent edge-triggered
memory (a `set` of currently-active opponent ids per condition, pruned
when an opponent drops out of the tracked set). The remaining two need
intelligence layers that don't exist yet (`RACING_LINE_DEGRADATION` →
Phase 15; `STRATEGY_FAILURE` → needs an actual strategy decision's outcome
to evaluate against) — `DETECTOR_STATUS` states this plainly and a test
(`test_detector_status_covers_every_event_type`) keeps the vocabulary and
the status map from drifting apart.

Undercut/overcut opportunity detection shares its threshold logic
(`classify_pit_timing_opportunity`) with `backend/strategy`'s UNDERCUT/
OVERCUT decision relabeling — one classifier, not two copies that could
disagree.

**Phase 12 (SC/VSC) is substantially this phase plus Phase 9's pit-loss
modeling** — `SAFETY_CAR`/`VSC` detection lives here, and event-aware
pit-loss reduction is a term in `backend/strategy`'s objective function
(`docs/STRATEGY.md`), not a separate module. `tests/test_sc_vsc_integration.py`
proves the full loop end-to-end: a simulator-injected SC period (via
`simulator/generator/core.py::FlagPeriod`) produces exactly one
`SAFETY_CAR` event on the rising edge, and the strategy engine reassesses
on that same frame, not at the next lap boundary.

`EventDetectionEngine.detect(state)` is called after every frame and does
a constant amount of comparison work — no per-packet simulation. Strategy
reassessment on important events is Phase 9's job (not built yet); this
engine only produces the events.
