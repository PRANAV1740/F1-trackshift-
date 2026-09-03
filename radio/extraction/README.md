# radio/extraction

**Status:** implemented (Phase 16).

Keyword/semantic extraction over transcribed radio text (`RadioIntentExtractor`).
Maps driver/engineer transcripts to `RadioIntent` vocabulary (`TYRE_GRAINING`, `TYRE_OVERHEATING`,
`TYRE_PUNCTURE`, `TRAFFIC_HEAVY`, `RAIN_REPORTED`, `BRAKE_BAL_ISSUE`, `STRATEGY_PIT_REQUEST`,
`STRATEGY_STAY_OUT_REQUEST`). Outputs structured `DriverRadioMessage` records.

Exercised in `tests/test_radio.py`.
