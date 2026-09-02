# radio/transcription

**Status:** not yet implemented (Phase 16).

Speech-to-text for team radio audio. Runs asynchronously and must never
block the telemetry decision loop (problem prompt section 18) -- treat this
as a background enrichment stream that occasionally attaches a
driver-reported signal to the race state, not as an input the strategy
engine waits on.
