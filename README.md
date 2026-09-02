# TrackShift 2026 — Race Intelligence Engine

> We don't predict tyres. We predict decisions.

A simulator-independent, real-time race intelligence engine. Tyre
degradation isolation (the official TrackShift 2026 problem) is one
intelligence layer inside a broader pipeline that turns noisy telemetry
into explainable strategic decisions — PIT / STAY_OUT / UNDERCUT / OVERCUT /
DEFEND / ATTACK, with a confidence, an expected outcome, and an
invalidation condition attached to every one.

Full architecture, design rationale, and documented assumptions: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Status

**Phase 1 of 18 complete** — repository skeleton, the common `RaceTelemetry`
schema, the `SourceAdapter` and `NormalizationStage` interfaces, and initial
tests. See the roadmap table in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#development-roadmap)
for what's next. Every directory with no code yet has its own `README.md`
explaining what it will hold and in which phase.

## Layout

```
frontend/    pitwall + hq dashboards, shared components/charts, track viz
backend/     ingestion → normalization → state → intelligence layers →
             events → strategy → prediction → websocket
models/      fitted ML components (tyre / pace / position / uncertainty)
simulator/   telemetry generator, seeded scenarios, injectable events, replay
radio/       async transcription + extraction (never blocks the decision loop)
evaluation/  backtesting, metrics, stress tests, latency instrumentation
tests/       unit + interface + scenario tests
docs/        architecture and assumptions
```

## Getting started

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

`pip install -e ".[dev]"` installs just enough to run today's code and
tests (`pydantic`, `pytest`). Heavier dependencies (`fastapi`, `numpy`,
`xgboost`, ...) are declared as optional extras in
[pyproject.toml](pyproject.toml) and get pulled in as later phases need
them — see the `[project.optional-dependencies]` groups (`api`, `ml`,
`realtime`).

## Engineering principles

- Physics-informed models and statistics first; gradient boosting where it
  measurably helps; deep learning only if it clears that bar.
- The strategy engine decides. An LLM, if used at all, only explains.
- No hard-coded demo numbers — every confidence, position, or time-loss
  value shown anywhere must trace back to real (or simulator-generated)
  input data flowing through the actual models.
- No claimed real-F1 or FIA integration, and no claimed production
  readiness. Interfaces are built so real integrations could attach later.
