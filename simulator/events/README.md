# simulator/events

**Status:** not yet implemented (Phase 10).

Injectable race events for the simulator: SC, VSC, rain, opponent pit,
undercut/overcut attempts, tyre cliff, strategy failure (problem prompt
section 20). Distinct from `backend/events`, which *detects* events from
telemetry -- this package *causes* them inside the simulator so detection
can be tested against a known ground truth.
