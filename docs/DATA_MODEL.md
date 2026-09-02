# Data Model

Reference for the common `RaceTelemetry` schema and the provenance/replay
types that wrap it. For *why* each design choice was made, see
[ARCHITECTURE.md](ARCHITECTURE.md) — this document is the field-by-field
reference; that one is the rationale.

## `RaceTelemetry` (`backend/telemetry/schema.py`)

One instant of telemetry for one car. Required: `source`,
`source_timestamp`, `car_id`, `lap`. Everything else is `Optional` because
no single source provides every field.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str | Currently `"0.1.0"` |
| `source` | `DataSource` | `REAL_CAR` \| `SIMULATOR` \| `HISTORICAL_REPLAY` |
| `source_timestamp` | datetime (UTC) | Set by the adapter, from the source |
| `ingest_timestamp` | datetime (UTC), optional | Set by `backend/ingestion` on arrival |
| `sequence_id` | int, optional | Adapter-assigned monotonic per-car counter, for ordering when timestamps jitter |
| `car_id` | str | Required |
| `lap` | int | Required |
| `sector` | int, optional | |
| `position` | int, optional | |
| `speed_kph`, `acceleration_ms2`, `longitudinal_acceleration_g`, `lateral_acceleration_g` | float, optional | |
| `throttle_pct`, `brake_pct`, `steering_angle_deg`, `gear`, `rpm` | optional | |
| `wheel_speeds` | `WheelSpeeds` | `front_left/right`, `rear_left/right` |
| `tyre_compound` | `TyreCompound`, optional | `SOFT/MEDIUM/HARD/INTERMEDIATE/WET/UNKNOWN` |
| `tyre_age_laps` | int, optional | Raw schema does not clamp negative values — see below |
| `tyre_temperature` | `TyreTemperatures` | One value per corner, not per thermal zone |
| `tyre_state` | `TyreState`, optional | Usually set downstream by tyre intelligence, not by raw sensors |
| `fuel_load_kg` | float, optional | |
| `gap_ahead_s`, `gap_behind_s` | float, optional | |
| `track_temperature_c`, `air_temperature_c`, `humidity_pct` | float, optional | |
| `weather` | `WeatherState`, optional | `DRY/DAMP/WET/UNKNOWN` |
| `rain_probability` | float, optional | 0-1 fraction, not clamped at schema level |
| `track_state` | `TrackState`, optional | Consolidated flag status; see coexistence note in ARCHITECTURE.md |
| `drs_available`, `drs_active` | bool, optional | |
| `safety_car`, `vsc`, `yellow_flag`, `red_flag` | bool | Default `False` |
| `pit_status` | `PitStatus`, optional | `ON_TRACK/ENTERING_PIT/IN_PIT_BOX/EXITING_PIT` |
| `pit_history` | list[`PitStop`] | |
| `opponent_states` | list[`OpponentState`] | Raw per-instant snapshot only |
| `sensor_confidence` | `SensorConfidence`, optional | Populated by normalization, `None` on raw ingest |
| `data_quality_flags` | list[str] | Issue tags added by normalization stages |

`model_config = ConfigDict(extra="allow")` — adapters may attach additional
fields not in this table without a schema change.

**Deliberately not validated at the schema level:** physical plausibility
(non-negative speed, non-negative tyre age, 0-1 `rain_probability`, etc.).
See ARCHITECTURE.md's schema design notes for why — that is the
normalization pipeline's job so it stays testable/tunable independently.

## Provenance types (`backend/normalization/base.py`)

- `NormalizationIssue(stage, severity, message, field)` — one thing a
  stage noticed.
- `FieldChange(stage, field, before, after, reason)` — one thing a stage
  actually modified.
- `NormalizationResult(raw_frame, normalized_frame, issues, changes,
  dropped_at_stage)` — returned per frame by `NormalizationPipeline.process()`.
  `raw_frame` is exactly what the adapter produced; `normalized_frame` is
  `None` if the frame was dropped. This is the full provenance record for
  one frame: source → raw values → what changed and why → final values →
  confidence (on `normalized_frame.sensor_confidence`).

## Derived features (`backend/normalization/stages.py::FeatureExtractionStage`)

Attached under `model_extra` (not first-class schema fields, to keep
"derived" visibly distinct from "raw telemetry"):

| Extra key | Meaning |
|---|---|
| `feature_speed_delta_kph` | `speed_kph - previous_frame.speed_kph` |
| `feature_accel_estimate_ms2` | Speed delta converted to m/s² over the elapsed time between frames |

## Replay descriptor (`backend/adapters/replay.py`)

`ReplayDescriptor(scenario_id, seed, config)` — frozen, with a derived
`config_hash` (sha256 of the canonicalized config, first 16 hex chars) and
`run_id` (`f"{scenario_id}:{seed}:{config_hash}"`). Any adapter whose
output must be reproducible implements `ReplayCapable.replay_descriptor()`.
