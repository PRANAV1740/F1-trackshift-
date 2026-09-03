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
| 7 | Baseline race trajectory | done | Forward pace/tyre-state projection + pit window, naive-labeled position/gap carry-forward. 117/117 tests passing |
| 8 | Event detection engine | done | 6/15 event types live (SC/VSC/tyre-cliff/degradation-accel/pace-drop/free-pit-window); rest honestly marked pending later phases. 127/127 tests passing |
| 9 | Strategy engine | done | Explicit objective function (projected time + risk + failure penalty), VSC/SC-aware pit loss, real off-by-one-lap bug found and fixed. 143/143 tests passing |
| 10 | Compound selection | done (core) | Candidate-compound comparison via the same objective function shipped as part of Phase 9's engine (comparing PIT->SOFT/MEDIUM/HARD is literally what `decide()` does) rather than a separate parallel module, to avoid duplicate logic. Track-temperature/weather/traffic/opponent-strategy refinements are honestly pending Phase 13/14 -- not yet factored in |
| 11 | Position / outcome prediction | done | Real Monte Carlo model, honestly reports insufficient_opponent_data in live use pending Phase 14. 154/154 tests passing |
| 12 | Safety car / VSC | done | Detection (Phase 8) + pit-loss modeling (Phase 9) already covered; added simulator FlagPeriod injection + full end-to-end reactive-loop test. 171/171 tests passing |
| 13 | Weather | done | Rain-probability trend detection (linear regression on observed history) feeding RAIN_INCOMING; simulator WeatherTransition injection. No live weather feed claimed. 171/171 tests passing |
| 14 | Opponent intelligence | done | First genuine multi-car simulation. RaceOrderTracker, OpponentSummary, undercut/overcut classifier, 6 new live events, UNDERCUT/OVERCUT wired into strategy, position prediction unlocked. Two significant bugs found+fixed (asyncio scheduling fairness, timestamp domain mismatch). 199/199 tests passing |
| 15 | Racing-line intelligence | done | Per-corner analysis (braking point/intensity, entry/apex/exit speed, line deviation, corner time loss), line classification (IDEAL/ATTACKING/DEFENSIVE), RACING_LINE_DEGRADATION event live. 211/211 tests passing |
| 16 | Radio intelligence | done | Async non-blocking RadioTranscriptionService, RadioIntentExtractor semantic keyword mapping, DriverRadioMessage schema, explicitly labeled deterministic demo mode. 217/217 tests passing |
| 17 | Human/AI disagreement | done | HumanAIDisagreementDetector comparing radio signals against telemetry estimates across 5 conflict types (tyre wear, cliff imminent, pit request vs strategy, rain vs dry, traffic vs gap). 223/223 tests passing |
| 18 | Simulator / replay engine | done | FlagPeriod (Phase 12), WeatherTransition (Phase 13), multi-car concurrent adapters (Phase 14), and PitStopEvent in-run pit stops (tyre compound/age reset, stationary box time, pit speed capping, pit history). 207/207 tests passing |
| 19 | Scenario suite | done | ScenarioDefinition catalog with 12 named, seeded scenarios (normal_race, tyre_cliff, vsc_pit_opportunity, sc_pit_opportunity, opponent_undercut, opponent_overcut, rain_arrival, heavy_traffic, telemetry_corruption, missing_telemetry, strategy_inferiority, driver_disagreement) and ScenarioRunner end-to-end execution. 232/232 tests passing |
| 20 | Backtesting / evaluation | done | BacktestEngine baseline vs AI strategy evaluation framework across all 12 scenarios. StrategyPerformanceMetrics, ScenarioEvaluationComparison, EvaluationReport metrics. 235/235 tests passing |
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
