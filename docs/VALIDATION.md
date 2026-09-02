# Validation

What has actually been verified, and how — kept honest and current as each
phase lands. This is the file to check before trusting any claim made
elsewhere in the docs.

## Phase 1 + foundation hardening

- 26/26 tests passing (`pytest`): schema construction/validation/
  permissiveness (7), adapter contract (3), normalization contract incl.
  per-frame provenance (6), replay descriptor hashing/equality (5),
  structured logging (3), plus fixtures.
- No models exist yet, so no model validation to report.
- No latency measurements yet — nothing runs end-to-end yet.
- No backtesting yet — no baseline to compare against yet.

## Phase 2 — telemetry ingestion

- 53/53 tests passing, up from 26. New coverage: the synthetic speed
  profile stays within the configured v_max and respects corner apex
  speeds (with small discretization slack); generator determinism given a
  fixed seed, including under severe injected noise; different seeds
  produce different noise patterns; tyre age and fuel evolve correctly
  across laps; the schema-validity of every generated frame; both concrete
  adapters (drop/duplicate packet handling, determinism, JSONL round-trip);
  the placeholder real-car adapter's `NotImplementedError` behavior; and
  ingestion's three error-isolation guarantees (malformed frame, failing
  adapter, failing sink each logged/counted without stopping the rest of
  the pipeline).
- Found and fixed during this phase, before it could compound: an initial
  design would have compared a fixed deterministic simulated-time anchor
  against real wall-clock `ingest_timestamp` as a "latency" figure, which
  is meaningless (they're different time domains) outside of realtime-paced
  delivery. Fixed by re-anchoring to real time only when
  `SimulatorAdapter(realtime=True)`; batch/test mode keeps the fixed
  anchor. Also caught before landing: noise injection was about to write
  simulator-only ground-truth tags into `RaceTelemetry.data_quality_flags`,
  which is documented as reserved for the normalization pipeline's own
  findings — moved to a separate `NoiseResult.injected` side channel instead.
- No claim that the physics model matches any real car's behavior — see
  the "illustrative constants" notes in `simulator/generator/physics.py`
  and `ground_truth.py`.

## What's intentionally NOT claimed

- No claim of real F1 telemetry access or FIA integration.
- No claim of production readiness.
- No claim that any predictive model outperforms a naive baseline until
  Phase 20 (backtesting) actually measures it. If it doesn't, that will be
  reported here plainly, not hidden.

This section grows as each phase lands; see [docs/PROGRESS.md](PROGRESS.md)
for phase-by-phase status and [docs/MODELS.md](MODELS.md) for per-model
validation methodology once models exist.
