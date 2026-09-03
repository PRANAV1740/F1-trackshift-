# frontend/pitwall

**Status:** implemented (Phase 22).

The pit-wall dashboard. Actionable, not informational: the current decision
(PIT: YES/NO, compound, window, confidence, expected position, position
gain, top reasons) is the dominant hero element on screen. Deliberately does not
surface raw telemetry -- that would compete with the decision for attention
(problem prompt section 24).

Includes Driver Radio Transcripts and Human / AI Disagreement Alert banners.
Implemented in `frontend/index.html` (Pit Wall tab) and `frontend/app.js`.
