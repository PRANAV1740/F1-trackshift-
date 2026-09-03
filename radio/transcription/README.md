# radio/transcription

**Status:** implemented (Phase 16).

Speech-to-text / text ingestion for team radio audio (`RadioTranscriptionService`).
Runs asynchronously and never blocks the core telemetry/decision pipeline (`await asyncio.sleep(0)` yield).
Features a deterministic text-based demo mode explicitly labeled on output (`is_demo_mode=True`).

Exercised in `tests/test_radio.py`.
