# backend/ingestion

**Status: implemented (Phase 2).**

`service.py::IngestionService` owns the adapter → normalization → downstream
pipeline: it runs every configured `SourceAdapter` concurrently, attaches
`ingest_timestamp` to each frame, performs structural validation (car_id
present -- NOT value-plausibility, which stays the normalization pipeline's
job), pushes the frame through a `NormalizationPipeline`, and fans the
result out to an `EventBus` (`bus.py`) and any number of "sinks" (plain
callables taking a `NormalizationResult`, sync or async). Phase 4's race
state estimator will plug in as a sink; nothing needs to change here for
that.

Error isolation is the core design point: a malformed frame, a failed
adapter, and a failed sink are each logged (structured, via
`backend/observability`) and counted in `IngestionMetrics`, but none of
them stops the rest of the pipeline. See `tests/test_ingestion_service.py`
for the exact guarantees exercised (malformed-frame counting, adapter
failure isolation, sink failure isolation, event-bus delivery).

Concrete adapters (`backend/adapters/`):

- `simulator_adapter.py::SimulatorAdapter` — wraps `simulator/generator`.
  Applies transport-level packet corruption (drop/delay/duplicate) on top
  of the generator's sensor-level noise; re-anchors timestamps to real
  wall-clock time only in `realtime=True` mode (see the docstring there for
  why fixed-seed determinism and wall-clock-comparable latency are
  otherwise in tension).
- `replay_adapter.py::ReplayAdapter` — replays a stored frame sequence
  (in-memory or JSONL file) in order, optionally paced to real time.
- `real_car_adapter.py::RealCarAdapter` — placeholder only. `connect()`/
  `stream()` raise `NotImplementedError` with a clear message; no real
  telemetry link exists or is claimed (engineering rule 8).
