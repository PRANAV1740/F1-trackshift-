# backend/strategy

**Status:** not yet implemented (Phase 8).

The decision-maker. Given the current race state and a triggering event,
outputs a direct, explainable decision (PIT / STAY_OUT / PIT_NEXT_LAP /
EXTEND / UNDERCUT / OVERCUT / DEFEND / ATTACK) with compound, window,
confidence, expected position, position gain, reasons, and an invalidation
condition (see problem prompt sections 13 and 27). This is the ONLY module
allowed to decide whether to pit -- `radio/` may transcribe and explain, an
LLM (if used at all) may narrate, but the decision itself is produced here
by a scored/optimized comparison over candidate strategies (see problem
prompt section 15 on the objective function), not by a language model.
