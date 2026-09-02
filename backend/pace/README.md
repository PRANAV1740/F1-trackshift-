# backend/pace

**Status:** not yet implemented (Phase 6).

Estimates expected clean-lap pace, downweighting traffic, yellow-flag laps,
safety-car laps, pit laps, and abnormal incidents, and predicts near-future
pace with an explicit per-effect breakdown (tyre contribution, traffic
contribution, fuel contribution -- see problem prompt section 8). Feeds
`backend/tyre` (pace model is one input to separating out the tyre
component) and `backend/strategy`.
