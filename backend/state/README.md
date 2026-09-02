# backend/state

**Status:** not yet implemented (Phase 4).

The continuously-updated `RaceState` for each car: current lap/position,
tyre state and degradation summary, pace vs expected pace, fuel/track
evolution, gaps, traffic, opponent summary, weather, SC/VSC, current
strategy, predicted pit window, expected finishing position, and an overall
confidence figure (see problem prompt section 6).

Updates whenever a normalized frame arrives from `backend/ingestion`, and is
the single object every intelligence module (`tyre`, `pace`, `racing_line`,
`opponents`, `weather`, `events`, `strategy`, `prediction`) reads from and
writes into. Keeping this the one shared state object -- rather than each
module keeping its own -- is what keeps the intelligence layers decoupled
from each other and from the frontend.
