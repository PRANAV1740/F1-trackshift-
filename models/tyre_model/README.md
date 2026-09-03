# models/tyre_model

**Status: implemented, but consolidated elsewhere — see note.**

The original repository plan split "fitted model" (`models/`) from
"business-logic estimator that uses it" (`backend/`). In practice, the
tyre degradation fit (`backend/tyre/model.py::fit_degradation_model`) and
its consumer (`backend/tyre/estimator.py`) are small enough, and tightly
enough coupled to `RaceState`, that splitting them across two directories
added indirection without benefit for a project this size — so the actual
fitting code lives in `backend/tyre/model.py`, not here. This is a
deliberate simplification, not an oversight; see
[docs/MODELS.md](../../docs/MODELS.md) for the full model writeup.
