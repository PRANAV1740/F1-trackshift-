# backend/weather

**Status:** not yet implemented (Phase 15).

Weather state: dry/damp/wet, rain probability, track wetting rate, drying
rate, and transition detection (see problem prompt section 17). No real
weather feed is assumed to exist -- in this prototype, weather state is
either taken from `RaceTelemetry.weather`/`rain_probability` as supplied by
whichever adapter is active, or injected by `simulator/scenarios` for
demo/testing. This is a documented limitation, not a claimed integration.
