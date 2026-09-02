"""The common `RaceTelemetry` schema.

Every source adapter (real car, simulator, historical/replay) translates its
native format into this schema and nothing else. Everything downstream --
normalization, state estimation, every intelligence module -- consumes only
`RaceTelemetry`, never a source-specific format. This is what makes the
platform simulator-independent: swap the adapter, the rest of the system
does not change.

Design decisions (see docs/ARCHITECTURE.md for the full rationale):

  * Units are explicit in field names (`speed_kph`, `fuel_load_kg`,
    `track_temperature_c`) instead of bare names like `speed`, so a unit
    mismatch is a naming bug, not a silent data bug.

  * The schema is intentionally permissive on numeric ranges. It does NOT
    reject a negative tyre age or an impossible speed at construction time.
    Detecting and handling implausible values is the explicit job of the
    normalization pipeline's dedicated stages (impossible-value detection,
    spike detection -- see backend/normalization/base.py), not the schema.
    Only structural correctness (types, enum membership, required fields)
    is enforced here.

  * `model_config = ConfigDict(extra="allow")` means adapters can attach
    additional source-specific fields without a schema change. Promote a
    field into the typed schema once two or more sources need it.

  * All timestamps are timezone-aware UTC. Adapters are responsible for
    converting source-local time to UTC before constructing a frame.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.1.0"


class DataSource(str, Enum):
    """Which kind of adapter produced this frame. See backend/adapters/base.py."""

    REAL_CAR = "REAL_CAR"
    SIMULATOR = "SIMULATOR"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"


class TyreCompound(str, Enum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"
    UNKNOWN = "UNKNOWN"


class TyreState(str, Enum):
    """Coarse tyre condition category.

    On real feeds this is rarely a raw sensor reading -- it is usually
    populated (or overwritten) by the tyre intelligence layer once a frame
    reaches the race state estimator. It lives on the common frame so every
    consumer reads it from one place regardless of who last set it.
    """

    NOMINAL = "NOMINAL"
    GRAINING = "GRAINING"
    BLISTERING = "BLISTERING"
    OVERHEATING = "OVERHEATING"
    CLIFF = "CLIFF"
    UNKNOWN = "UNKNOWN"


class WeatherState(str, Enum):
    DRY = "DRY"
    DAMP = "DAMP"
    WET = "WET"
    UNKNOWN = "UNKNOWN"


class TrackState(str, Enum):
    """Consolidated race-control status.

    Some feeds expose flag state only as this single enum; others expose it
    only as separate booleans (`safety_car`, `vsc`, `yellow_flag`,
    `red_flag` below). Both are part of the schema because adapters differ
    in what they natively provide; reconciling the two into one consistent
    view is a normalization concern, not a schema concern.
    """

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    SAFETY_CAR = "SAFETY_CAR"
    VIRTUAL_SAFETY_CAR = "VIRTUAL_SAFETY_CAR"
    RED_FLAG = "RED_FLAG"
    UNKNOWN = "UNKNOWN"


class PitStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    ENTERING_PIT = "ENTERING_PIT"
    IN_PIT_BOX = "IN_PIT_BOX"
    EXITING_PIT = "EXITING_PIT"


class WheelSpeeds(BaseModel):
    front_left: Optional[float] = None
    front_right: Optional[float] = None
    rear_left: Optional[float] = None
    rear_right: Optional[float] = None


class TyreTemperatures(BaseModel):
    """One reading per corner.

    Real thermal-camera feeds often report inner/mid/outer zones per tyre;
    this prototype simplifies that to a single value per corner. Documented
    simplification -- revisit if a source adapter needs the finer detail.
    """

    front_left_c: Optional[float] = None
    front_right_c: Optional[float] = None
    rear_left_c: Optional[float] = None
    rear_right_c: Optional[float] = None


class PitStop(BaseModel):
    lap: int
    entry_timestamp: Optional[datetime] = None
    exit_timestamp: Optional[datetime] = None
    stationary_time_s: Optional[float] = None
    total_pit_loss_s: Optional[float] = None
    compound_before: Optional[TyreCompound] = None
    compound_after: Optional[TyreCompound] = None


class OpponentState(BaseModel):
    """A lightweight, per-frame snapshot of one opponent.

    This is raw/observed state only (what a telemetry or timing feed
    directly gives you). Derived intelligence about an opponent -- pit
    probability, undercut threat, estimated degradation -- is computed by
    backend/opponents in a later phase and is not part of the raw frame.
    """

    car_id: str
    position: Optional[int] = None
    gap_s: Optional[float] = None
    compound: Optional[TyreCompound] = None
    tyre_age_laps: Optional[int] = None


class SensorConfidence(BaseModel):
    """Per-field confidence scores attached by the normalization pipeline.

    Absent (`None`) on a freshly ingested raw frame; populated once the
    frame has passed through the sensor-confidence-scoring stage. A score
    of 1.0 means "fully trusted", 0.0 means "do not trust this reading".
    """

    overall: float = 1.0
    speed: float = 1.0
    tyre_temperature: float = 1.0
    position: float = 1.0


class RaceTelemetry(BaseModel):
    """One instant of telemetry for one car, in the common schema.

    Required fields are deliberately minimal (identity + timing). Everything
    else is Optional because no single source provides every field, and a
    frame missing a sensor reading is normal, not an error.
    """

    model_config = ConfigDict(extra="allow")

    # --- Envelope / provenance -------------------------------------------------
    schema_version: str = SCHEMA_VERSION
    source: DataSource
    source_timestamp: datetime
    ingest_timestamp: Optional[datetime] = None
    sequence_id: Optional[int] = Field(
        default=None,
        description="Monotonic per-car counter from the adapter, for ordering "
        "and duplicate-detection when timestamps alone are unreliable.",
    )

    # --- Identity ----------------------------------------------------------
    car_id: str
    lap: int
    sector: Optional[int] = None
    position: Optional[int] = None

    # --- Motion --------------------------------------------------------------
    speed_kph: Optional[float] = None
    acceleration_ms2: Optional[float] = None
    longitudinal_acceleration_g: Optional[float] = None
    lateral_acceleration_g: Optional[float] = None

    # --- Driver inputs -------------------------------------------------------
    throttle_pct: Optional[float] = None
    brake_pct: Optional[float] = None
    steering_angle_deg: Optional[float] = None
    gear: Optional[int] = None
    rpm: Optional[float] = None

    wheel_speeds: WheelSpeeds = Field(default_factory=WheelSpeeds)

    # --- Tyres -----------------------------------------------------------------
    tyre_compound: Optional[TyreCompound] = None
    tyre_age_laps: Optional[int] = None
    tyre_temperature: TyreTemperatures = Field(default_factory=TyreTemperatures)
    tyre_state: Optional[TyreState] = None

    # --- Fuel ------------------------------------------------------------------
    fuel_load_kg: Optional[float] = None

    # --- Gaps ------------------------------------------------------------------
    gap_ahead_s: Optional[float] = None
    gap_behind_s: Optional[float] = None

    # --- Environment -----------------------------------------------------------
    track_temperature_c: Optional[float] = None
    air_temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    weather: Optional[WeatherState] = None
    rain_probability: Optional[float] = None

    track_state: Optional[TrackState] = None

    # --- DRS ---------------------------------------------------------------------
    drs_available: Optional[bool] = None
    drs_active: Optional[bool] = None

    # --- Flags (see TrackState docstring for why these coexist with it) --------
    safety_car: bool = False
    vsc: bool = False
    yellow_flag: bool = False
    red_flag: bool = False

    # --- Pit -----------------------------------------------------------------
    pit_status: Optional[PitStatus] = None
    pit_history: list[PitStop] = Field(default_factory=list)

    # --- Opponents -----------------------------------------------------------
    opponent_states: list[OpponentState] = Field(default_factory=list)

    # --- Data quality (populated by normalization, not by adapters) ------------
    sensor_confidence: Optional[SensorConfidence] = None
    data_quality_flags: list[str] = Field(
        default_factory=list,
        description="Issue tags added by normalization stages, e.g. "
        "'INTERPOLATED', 'SPIKE_REJECTED', 'DUPLICATE'. Empty on raw ingest.",
    )
