# backend/prediction

**Status:** not yet implemented (Phase 9).

Predicts a finishing-position *distribution* per car (not just a point
estimate or a lap time), e.g. `P5: 42%, P6: 37%, P7: 15%, P8+: 6%`, plus
expected position, position gain/loss, risk, and uncertainty (see problem
prompt section 14). Used by `backend/strategy` to compare candidate
strategies against the risk-aware objective (section 15) and by
`models/position_model` for the underlying fitted component, if any.
