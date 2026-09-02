# backend/ingestion

**Status:** not yet implemented (Phase 2).

Owns the loop that pulls frames from one or more `SourceAdapter`s
(`backend/adapters/base.py`), pushes each through the `NormalizationPipeline`
(`backend/normalization/base.py`), and hands normalized frames to the race
state estimator (`backend/state`). This is the module that turns "adapters"
and "normalization" from two libraries into one running pipeline.

Expected responsibilities once implemented:

- Own adapter lifecycle (connect/disconnect, reconnect on failure).
- Fan frames from possibly-multiple adapters into one ordered stream per car.
- Own the `NormalizationPipeline` instance and its per-car contexts.
- Emit normalized frames onward (to state estimation) and expose ingestion
  health/latency for `backend/websocket` and `evaluation/latency`.
