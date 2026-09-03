# backend/weather

**Status: implemented (Phase 13).**

No live weather feed exists or is claimed. `RaceTelemetry.weather`/
`rain_probability` (populated by whichever adapter is active — the
simulator via `GeneratorConfig.weather_transitions`, in this prototype) is
already the clean integration point for a real one; this module never
invents a separate weather-specific adapter.

`model.py::assess_weather` tracks the actual trend in observed
`rain_probability` (`numpy.polyfit` over a bounded per-car history, not
just the instantaneous value) to detect wetting/drying transitions.
`estimator.py::WeatherIntelligenceEstimator` builds that history
incrementally. Feeds `backend/events`' `RAIN_INCOMING` detector.
