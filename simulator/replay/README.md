# simulator/replay

**Status:** not yet implemented (Phase 10).

Deterministic replay of a previously generated or recorded telemetry
stream, exposed through a `SourceAdapter` with `source_type =
HISTORICAL_REPLAY`. Backs `evaluation/backtesting` (replaying historical
data to compare baseline vs. AI strategy) and the `POST /api/replay/start`
API (problem prompt section 32).
