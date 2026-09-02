# simulator/generator

**Status: implemented (Phase 2 core; extended with events/opponents in
Phase 18).**

Produces a deterministic, physics-informed synthetic telemetry stream for
one car's stint. Given the same `(GeneratorConfig, seed)`, `frames()`
always yields byte-identical output -- see
`tests/test_simulator_generator.py`.

- **`track.py`** — a fixed, fully synthetic 14-corner layout
  (`default_track()`), invented for this project. No real circuit geometry
  is used anywhere (engineering rule 8).
- **`physics.py`** — a simplified point-mass "double-pass" lap simulation
  (backward braking pass + forward traction/power pass) producing a
  speed-vs-distance profile. All constants (mass, power, braking/traction
  limits) are illustrative round numbers, documented as such, not sourced
  from real car data.
- **`ground_truth.py`** — the *known* fuel-effect, track-evolution, and
  per-compound degradation models used to generate data. These are
  deliberately never imported by `backend/tyre` or `backend/pace` — only by
  the generator itself and by validation/test code, so that Phase 5/6
  estimators can be checked against a known answer without being able to
  "cheat" by importing it.
- **`noise.py`** — configurable sensor-level noise (speed/steering/brake/
  throttle/temperature jitter, spikes, timestamp jitter) plus packet-fate
  decisions (dropped/delayed/duplicated), all driven by a caller-supplied
  seeded `random.Random` for determinism. `NoiseConfig.clean()` /
  `.moderate()` / `.severe()` are three ready-made presets.
- **`core.py`** — `TelemetryGenerator`, which ties the above together into
  a per-tick `RaceTelemetry` stream: speed from the physics profile scaled
  by a pace multiplier derived from the ground-truth effects, with
  throttle/brake/steering/gear/rpm/tyre-temperature/wheel-speed derived
  per tick from that speed profile and corner geometry.

**Consumed only through `backend/adapters/simulator_adapter.py`** — no
other backend code imports this package directly, which is what keeps the
platform simulator-independent (see docs/ARCHITECTURE.md).

**Known simplifications** (all deliberate, for a hackathon-grade
prototype): fuel and degradation are modeled as a uniform pace multiplier
applied to the whole lap's speed profile rather than affecting each corner
individually; there is no multi-car interaction yet (opponents/gaps come in
Phase 14/18); there are no pit stops yet (continuous single-stint only,
until Phase 18).
