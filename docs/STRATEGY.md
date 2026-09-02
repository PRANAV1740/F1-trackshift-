# Strategy Engine

**Status: not yet populated.** The strategy engine lands in Phase 9
(decision types, objective function) and Phase 10 (compound selection).
This file will document, without hiding the mathematics:

- The exact strategy objective function (expected race time + risk penalty
  + failure probability penalty, or the equivalent outcome-oriented
  formulation actually implemented) and why it's an appropriate objective.
- Every supported decision type (`PIT`, `STAY_OUT`, `PIT_NEXT_LAP`,
  `EXTEND`, `UNDERCUT`, `OVERCUT`, `ATTACK`, `DEFEND`) and the conditions
  under which each is produced.
- How compound selection factors in remaining distance, tyre life,
  degradation, pace, track/weather, traffic, pit loss, opponent strategy,
  and position.
- The explicit boundary: the strategy engine decides; an LLM (if used at
  all) only explains. See ARCHITECTURE.md's module-boundary rules.
- What invalidates a decision, and how confidence is computed.

Nothing below this line is real until the corresponding phase lands.
