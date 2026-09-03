# evaluation/backtesting

**Status:** implemented (Phase 20).

Compares baseline strategy vs. AI strategy over historical/replayed scenario data (`BacktestEngine`):
- Measures finish position, total race time, pit timing, tyre life, positions gained/lost, decision latency, false alerts.
- Evaluates performance across all 12 named scenarios.
- Explicitly states where AI outperforms naive baseline (tyre cliff, VSC/SC opportunities, rain arrival, opponent undercut/overcut) and where baseline performs similarly (steady dry race).

Exercised in `tests/test_backtesting.py`.
