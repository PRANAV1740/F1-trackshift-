# backend/events

**Status:** not yet implemented (Phase 7).

Watches the race state for state transitions worth reacting to (see problem
prompt section 11 for the full event vocabulary: `TYRE_CLIFF_APPROACHING`,
`OPPONENT_PITTING`, `UNDERCUT_OPPORTUNITY`, `SAFETY_CAR`, `RAIN_INCOMING`,
`POSITION_THREAT`, etc.) and triggers `backend/strategy` reassessment.
Deliberately event-driven rather than a fixed-interval re-simulation loop:
strategy reassessment happens because something changed, not on a timer.
