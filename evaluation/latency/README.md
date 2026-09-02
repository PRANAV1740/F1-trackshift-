# evaluation/latency

**Status:** not yet implemented (Phase 17, instrumented starting whichever
phase first has an end-to-end pipeline to measure).

Measures decision latency end-to-end and per stage (ingestion,
normalization, state update, tyre model, event detection, strategy,
prediction, WebSocket, frontend), against the target of &lt;2s and hard
ceiling of &lt;5s (problem prompt section 23).
