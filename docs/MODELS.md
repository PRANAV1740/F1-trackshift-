# Models

Every model used for anything beyond deterministic bookkeeping is
documented here: inputs, features, target, training method, validation
method, metrics, and limitations. If a model can't be documented this way,
it doesn't belong in the system.

## Tyre degradation model (`backend/tyre/model.py`)

**Used by:** `backend/tyre/estimator.py::TyreDegradationEstimator`, which
writes results into `RaceState`'s `estimated_degradation_s`,
`degradation_rate_s_per_lap`, `degradation_acceleration_s_per_lap2`,
`tyre_cliff_probability`, `remaining_tyre_life_laps`.

**Kind:** physics-assumption + weighted linear regression (piecewise, via
grid search over candidate cliff laps). No gradient boosting or deep
learning — an interpretable closed-form fit is sufficient for this
problem's actual shape (a linear term plus one breakpoint), and adding a
black-box model on top would not be justified by anything measured.

**The decomposition:** `lap_time = base_pace + fuel_effect + track_evolution
+ degradation + noise`. `fuel_effect` and `track_evolution` are computed
via small, fixed, **assumed** functions
(`assumed_fuel_effect_s`, `assumed_track_evolution_gain_s`), not fit from
data — deliberately, because within a single stint, tyre age, lap number,
fuel burned, and track evolution are all near-perfectly collinear
functions of the same lap counter, making a fully-free multi-coefficient
fit statistically unidentifiable. Treating fuel/evolution as known reduces
the fitting problem to one free curve (degradation vs. age), which *is*
identifiable from a single stint. See the module docstring in
`backend/tyre/model.py` for the full argument.

**Inputs / features:** per completed lap (a `TyreObservation`): tyre age
(laps since fitted/last reset), fuel load at lap start, lap number, lap
time, and a confidence weight (from `RaceState.completed_laps`'
`avg_confidence`, itself derived from `RaceTelemetry.sensor_confidence`).
Laps that are pit laps, non-green-flag, or below a confidence threshold are
excluded before fitting (`backend/tyre/estimator.py::_is_usable`) — basic
robust-statistics practice, not a full "clean pace" model (that's Phase 6).

**Target:** the lap-time residual after removing assumed fuel/evolution
effects, as a function of tyre age: `linear_rate * age + cliff_coeff *
max(0, age - cliff_lap)²`.

**Training method:** weighted least squares (`numpy.linalg.lstsq`),
refit per car per compound whenever new completed laps arrive (event-driven,
not per-telemetry-tick). `cliff_lap` is chosen by grid search over
candidate values (3–44 laps), each scored by weighted RSS — a simple,
fully interpretable form of piecewise regression.

**Uncertainty:** `residual_std_s` from the fit's residual variance.
`cliff_posterior` — a discrete probability distribution over candidate
cliff laps — comes from treating each candidate's RSS as an (unnormalized)
Gaussian negative log-likelihood: under i.i.d. Gaussian residuals,
likelihood ∝ exp(-RSS / 2σ²), so `softmax(-RSS / 2σ²)` over the grid *is*
the (uniform-prior) posterior over which candidate is correct — a genuine
Bayesian argument, not just a heuristic score, though it does inherit the
Gaussian-residual assumption. `cliff_probability_within(age, lookahead)`
sums posterior mass for candidates within reach.

**Validation** (see `tests/test_tyre_model.py`, numbers logged in
docs/VALIDATION.md): two tiers, deliberately separate —

1. A controlled synthetic test where lap times are generated from the
   *exact same* assumed fuel/evolution functions the fitter uses (i.e. no
   model misspecification) — isolates whether the regression machinery
   itself is correct. Recovers the injected rate to ±0.015s/lap and the
   injected cliff lap to ±5 laps.
2. A realistic test using the actual simulator (whose ground-truth
   fuel/degradation constants are deliberately *different* from this
   module's assumed ones — see `simulator/generator/ground_truth.py` vs.
   `backend/tyre/model.py`), pooling two independently-generated stints
   (the second using `GeneratorConfig.starting_lap` to honestly represent a
   later stint in a longer race — this is what breaks the identifiability
   problem; see the docstring in `tests/test_tyre_model.py` for a case
   where faking the offset only at the fitting step, without the
   underlying data reflecting it, produced a *negative* correlation before
   this was fixed). Validated by shape (Pearson correlation between fitted
   and true degradation curves across the observed age range), not exact
   numeric recovery — because exact recovery isn't the honest claim to
   make when the fuel/evolution assumptions are intentionally imperfect.

**Known limitations (documented, not hidden):**

- The `cliff_lap` **point estimate** is unreliable when no observations
  reach anywhere near the true cliff (e.g. a 20-lap stint on a compound
  whose true cliff is at lap 22): the grid search has no data to
  distinguish "cliff far away" from "cliff very far away," so the point
  estimate can land far from the truth even though the overall predicted
  degradation *curve* still tracks the truth well within the observed
  range (correlation ~0.97, MAE ~0.15s in the logged validation run). This
  is why `cliff_posterior` exists as a full distribution rather than a
  single number — in that scenario it is appropriately diffuse (no
  candidate carries more than ~3% of the posterior mass) rather than
  falsely confident, and `cliff_probability_within()` correctly reports
  moderate-to-low probability rather than near-certainty.
- Fuel effect and track evolution are assumed, not fit — any error in
  those assumptions biases the degradation estimate. This bias is exactly
  what `evaluation/backtesting` (Phase 20) should be able to surface given
  real or higher-fidelity data.
- "Driver variation" (explicitly listed in the decomposition the problem
  statement asks for) is not modeled at all; its effect is absorbed into
  the residual noise term, and therefore into `residual_std_s` and the
  cliff posterior's spread — the model doesn't claim to separate it out,
  it just doesn't let it silently bias the degradation estimate beyond
  making the uncertainty wider.
- Requires data from more than one stint (or car) to be statistically
  identifiable at all, per the collinearity argument above. A single,
  uninterrupted stint's data alone is not sufficient — the estimator will
  still fit something (`fit_degradation_model` doesn't refuse to run on
  single-stint data), but it should not be trusted as separating
  degradation from fuel/evolution in that case. This is a fundamental
  identifiability limit, not an implementation gap.

## Pace model (`backend/pace/model.py`)

**Used by:** `backend/pace/estimator.py::PaceIntelligenceEstimator`, which
writes into `RaceState`'s `current_pace_s`, `expected_clean_pace_s`,
`pace_delta_s`, `pace_trend_s_per_lap`.

**Kind:** direct composition of the tyre model's decomposition (no
independent fitting) plus one simple linear regression (`numpy.polyfit`,
degree 1) for the trend slope. Not a separate statistical model of pace in
its own right — deliberately, since Phase 5 already produces a validated
decomposition; re-deriving it here would be duplicate, unjustified
complexity.

**Inputs / features:** `RaceState.completed_laps`, current lap/tyre-age/
fuel, and (when available) Phase 5's fitted `DegradationEstimate` for this
car and compound.

**Target / output:** `expected_clean_pace_s` = `base_pace_s +
assumed_fuel_effect_s(current_fuel) + assumed_track_evolution_gain_s
(current_lap) + degradation_estimate.degradation_at(current_age)` when a
fitted degradation curve exists; otherwise the mean of the last
`TREND_WINDOW_LAPS` (5) clean laps, clearly labeled via
`PaceEstimate.source ∈ {"tyre_model", "rolling_average",
"insufficient_data"}` — callers must not conflate the two. `pace_trend_s_per_lap`
is the OLS slope of lap time vs. lap number over the same recent-clean-laps
window (requires ≥3 clean laps, else `None`).

**Validation:** unit tests (`tests/test_pace_model.py`) cover both sources,
the delta computation, the clean-lap trend slope against a known synthetic
gradient (recovers a 0.5s/lap injected trend to ±0.01s/lap), and that an
unclean lap (e.g. a pit lap) still shows up in `current_pace_s` but is
excluded from the rolling average and trend. No separate ground-truth
validation beyond Phase 5's, since this model doesn't introduce new fitted
parameters of its own.

**Known limitations:** the rolling-average fallback (used early in a
stint, before Phase 5 has enough laps to fit) does not correct for fuel
burn or track evolution at all — it is a genuinely weaker estimate, which
is why it's labeled distinctly rather than blended silently with the
tyre-model-based one. "Heavy traffic" and "major incidents" are excluded
from the clean-lap set only via `avg_confidence` and track-state signals
already on `LapRecord` — there is no dedicated traffic classifier; that
depends on gap-to-car-ahead data, which becomes available with
`backend/opponents` in Phase 14.

## Position prediction model (`backend/prediction/model.py`)

**Used by:** `backend/prediction/estimator.py::PositionPredictionEstimator`,
writing into `RaceState.predicted_finishing_position`.

**Kind:** Monte Carlo simulation (`numpy.random.default_rng`), not a
learned model. Sample this car's and each opponent's projected remaining-
race-time from independent Normal distributions, rank each draw, tally
the empirical distribution over finishing positions.

**Inputs:** `TimeDistribution(car_id, mean_s, std_s)` for this car (built
from `backend/strategy`'s chosen candidate: mean = `chosen_projected_time_s`,
std = `chosen_residual_std_s × sqrt(chosen_remaining_laps)`) and a list of
the same for opponents.

**Target/output:** `position_probabilities: dict[int, float]` (sums to
1.0), `expected_position` (probability-weighted mean), `position_gain_expected`
(current position minus expected), `risk_of_losing_positions` (fraction of
draws finishing worse than the current position).

**Validation:** `tests/test_prediction_model.py` — a dominant car wins P1
>95% of draws, a much-slower car finishes last >95% of draws, a close
field spreads probability across multiple positions, probabilities always
sum to 1.0, `expected_position` matches manual recomputation from the
distribution, and results are deterministic given the same seed.

**Known limitation, stated plainly:** this model has **no live opponent
data source**. `PositionPredictionEstimator` always returns
`source="insufficient_opponent_data"` in current usage because the
simulator only produces one car (Phase 2/18) and there is no opponent pace
model (Phase 14) to build real opponent `TimeDistribution`s from. The
Monte Carlo mechanism is real and tested; what's missing is a live input,
not the math. This is the single clearest instance in the project of "the
interface and the model exist; the number is not shown until real data can
support it."
