# simulator/scenarios

**Status:** implemented (Phase 19).

Named, seeded scenario definitions (12 total):
1. `normal_race`: clean 20-lap green flag stint.
2. `tyre_cliff`: soft tyre stint hitting cliff near lap 16.
3. `vsc_pit_opportunity`: VSC deployed laps 10-12.
4. `sc_pit_opportunity`: SC deployed laps 12-15.
5. `opponent_undercut`: 2-car simulation with undercut opportunity.
6. `opponent_overcut`: 2-car simulation with overcut opportunity.
7. `rain_arrival`: rain transition at lap 8.
8. `heavy_traffic`: 2-car simulation in dirty air behind slower car.
9. `telemetry_corruption`: severe noise, drops, duplicates.
10. `missing_telemetry`: packet drops testing LOCF imputation.
11. `strategy_inferiority`: stay-out strategy vs AI timely pit stop.
12. `driver_disagreement`: driver reports severe wear while telemetry shows clean.

Each scenario is identified by `(scenario_id, seed)` and fully reproducible via `ScenarioRunner`.
Exercised in `tests/test_scenarios.py`.
