# simulator/generator

**Status:** not yet implemented (Phase 10).

Generates realistic-looking `RaceTelemetry` streams, and is consumed
through a `SourceAdapter` (`backend/adapters/base.py`, `source_type =
SIMULATOR`) exactly like any other source -- production code never imports
this package directly. Includes the configurable noise injection described
in problem prompt section 5 (speed/brake/steering/temperature noise,
timestamp jitter, missing packets, sensor spikes, delayed telemetry).
