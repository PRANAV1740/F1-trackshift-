# simulator/scenarios

**Status:** not yet implemented (Phase 10, exercised by the scenario tests
of Phase 21).

Named, seeded scenario definitions (normal race, tyre cliff, VSC pit
opportunity, opponent undercut, rain arrival, heavy traffic, noisy
telemetry, dropped packets, strategy inferiority, driver/telemetry
disagreement -- problem prompt section 21) built on top of
`simulator/generator` and `simulator/events`. Each scenario is identified
by `(scenario_id, seed)` and must be fully reproducible from that pair
(problem prompt section 20).
