# evaluation/latency

**Status:** implemented (Phase 21).

Measures decision latency end-to-end and per stage:
- Ingestion & Normalization
- State Estimation
- Tyre Degradation Fitting
- Pace Intelligence
- Racing Line Intelligence
- Opponent Intelligence
- Position Prediction
- Strategy Decision
- Event Detection

Enforces performance target of <2.0s mean decision latency and hard ceiling of <5.0s max decision latency under heavy tick rates (`LatencyBenchmark`).

Exercised in `tests/test_latency.py`.
