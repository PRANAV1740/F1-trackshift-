# Build Progress — Autonomous Session Log

This file is the working ledger for the autonomous build authorized on
2026-09-03. It is updated as each phase lands. See
[docs/ARCHITECTURE.md](ARCHITECTURE.md) for the stable architecture
description and [docs/VALIDATION.md](VALIDATION.md) for what's actually
been verified.

## Status legend
`todo` not started · `wip` in progress · `done` implemented + tested ·
`deferred` intentionally scoped out with reasons given

| Phase | Scope | Status | Notes |
|---|---|---|---|
| 1 | Repository + schemas | done | Reviewed critically this session; see "Foundation hardening" below |
| 1.5 | Foundation hardening | done | Provenance, replay contract, observability. 26/26 tests passing |
| 2 | Telemetry ingestion | done | IngestionService, EventBus, SimulatorAdapter, ReplayAdapter, RealCarAdapter placeholder, physics-informed simulator/generator. 53/53 tests passing |
| 3 | Normalization / data quality | done | 10 concrete stages implemented and unit+integration tested. 75/75 tests passing |
| 4 | Race state estimator | done | Incremental per-car RaceState + RaceStateEstimator, wired as an ingestion sink. 83/83 tests passing |
| 5 | Tyre degradation intelligence | done | Assumed-physics decomposition + WLS degradation fit with grid-searched cliff and Bayesian-flavored posterior. 98/98 tests passing |
| 6 | Pace intelligence | done | Composes Phase 5's decomposition at current state + rolling-average fallback + trend slope. 108/108 tests passing |
| 7 | Baseline race trajectory | todo | |
| 8 | Event detection engine | todo | |
| 9 | Strategy engine | todo | |
| 10 | Compound selection | todo | |
| 11 | Position / outcome prediction | todo | |
| 12 | Safety car / VSC | todo | |
| 13 | Weather | todo | |
| 14 | Opponent intelligence | todo | |
| 15 | Racing-line intelligence | todo | |
| 16 | Radio intelligence | todo | |
| 17 | Human/AI disagreement | todo | |
| 18 | Simulator / replay engine | todo | |
| 19 | Scenario suite | todo | |
| 20 | Backtesting / evaluation | todo | |
| 21 | Latency engineering | todo | |
| 22 | Pit wall | todo | |
| 23 | HQ | todo | |
| 24 | Track visualization | todo | |
| 25 | Observability | todo | |
| 26 | Failure handling | todo | |
| 27 | Security / code quality | todo | |
| 28 | Testing (full pass) | todo | |
| 29 | Demo mode | todo | |
| 30 | Final audit | todo | |

## Foundation hardening (pre-Phase-2 fixes)

Issues found on critical review of Phase 1, and what's being done about
each:

1. **No telemetry provenance.** Normalization stages returned a modified
   frame with no record of the original raw values or what specifically
   changed. Fixed by adding `FieldChange` records and a `NormalizationResult`
   envelope (raw frame + normalized frame + changes + issues + confidence)
   returned from the pipeline instead of a bare frame.
2. **No deterministic-replay contract.** Nothing captured `(scenario_id,
   seed, config)` as a first-class, hashable descriptor. Added
   `backend/adapters/replay.py::ReplayDescriptor` + `ReplayCapable` protocol,
   implemented by the simulator and replay adapters from Phase 2 onward.
3. **No structured logging / no consistent "never silently swallow
   errors" mechanism.** Added `backend/observability/logging.py` as a
   cross-cutting utility used from Phase 2 onward.
4. **Private-attribute test coupling.** `test_normalization_interface.py`
   reached into `pipeline._contexts`. Added a public `get_context()` accessor.

Everything else in Phase 1 (the `RaceTelemetry` schema, the `SourceAdapter`
ABC, the general pipeline shape) held up under review and is kept as-is.
