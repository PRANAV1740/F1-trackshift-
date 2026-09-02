# Models

Every model used for anything beyond deterministic bookkeeping is
documented here: inputs, features, target, training method, validation
method, metrics, and limitations. If a model can't be documented this way,
it doesn't belong in the system (see engineering rule: "if a model cannot
be justified, do not add it").

**Status: not yet populated.** No model exists yet. This file will be
filled in as each of the following lands, in order:

- Tyre degradation model (Phase 5)
- Pace / clean-lap model (Phase 6)
- Position / outcome prediction model (Phase 11)
- Compound selection scoring (Phase 10)

Each entry, once added, will follow this template:

```
## <Model name>

**Used by:** <module>
**Kind:** physics-informed / statistical / gradient-boosted / other (never
deep learning unless a measured improvement over the simpler baseline is
shown and documented here)

**Inputs / features:** ...
**Target:** ...
**Training method:** ...
**Validation method:** ...
**Metrics:** ...
**Known limitations:** ...
```
