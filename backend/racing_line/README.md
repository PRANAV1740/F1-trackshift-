# backend/racing_line

**Status:** not yet implemented (Phase 13).

Track representation plus per-corner analysis: braking point/intensity,
entry/apex/exit speed, apex position, steering input, throttle pickup,
racing-line deviation vs. a reference line, and estimated time loss per
corner (see problem prompt section 9). Also classifies ideal / attacking /
defensive line, feeding strategic reasoning in `backend/strategy` (e.g.
"raw pace advantage exists but overtake probability is low, so prefer
undercut over on-track attack").
