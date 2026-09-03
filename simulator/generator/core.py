"""Deterministic synthetic telemetry generator for one car.

Given a seed and a `GeneratorConfig`, `TelemetryGenerator.frames()` produces
the exact same sequence of `RaceTelemetry` frames every time -- the core of
the deterministic-replay contract (backend/adapters/replay.py). It combines:

  * a physics-informed speed profile around the synthetic track
    (simulator/generator/physics.py), scaled by a pace multiplier derived
    from ground-truth fuel/degradation/track-evolution effects
    (simulator/generator/ground_truth.py) so lap time behaves the way those
    models say it should;
  * per-tick derived channels (throttle/brake/steering/gear/rpm/tyre temps)
    computed from the speed profile with simple, documented approximations;
  * sensor-level value noise (simulator/generator/noise.py).

Packet-level transport corruption (dropped/delayed/duplicated packets) is
NOT applied here -- that's a delivery concern, layered on by
`backend/adapters/simulator_adapter.py`. This module's job is "what the
sensors saw", not "what made it across the wire".
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator

from backend.telemetry.schema import (
    RaceTelemetry,
    DataSource,
    PitStatus,
    PitStop,
    TrackState,
    TyreCompound,
    TyreTemperatures,
    WeatherState,
    WheelSpeeds,
)
from simulator.generator.ground_truth import (
    COMPOUND_MODELS,
    fuel_effect_s,
    track_evolution_gain_s,
)
from simulator.generator.noise import NoiseConfig, apply_noise
from simulator.generator.physics import build_speed_profile, kph_to_ms, ms_to_kph
from simulator.generator.track import SyntheticTrack, default_track

DEFAULT_START_TIME = datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

_GEAR_SPEED_THRESHOLDS_KPH = [0, 60, 100, 140, 180, 220, 260, 300]

SC_SPEED_CAP_FRACTION = 0.40
VSC_SPEED_CAP_FRACTION = 0.70


@dataclass(frozen=True)
class FlagPeriod:
    """An injectable SC/VSC period, by GLOBAL lap number (see
    `GeneratorConfig.starting_lap`) -- inclusive of both ends.

    Speed is scaled down by a fixed fraction of the profile speed for the
    duration (documented simplification: real SC/VSC pace is governed by
    delta-time compliance and pit-lane-adjacent limits, not a flat fraction
    of racing speed; this is a hackathon-grade approximation, not a claim
    of matching real SC/VSC pace behavior).
    """

    start_lap: int
    end_lap: int
    kind: str  # "SC" or "VSC"
    speed_cap_fraction: float | None = None


@dataclass(frozen=True)
class WeatherTransition:
    """Weather from `start_lap` (global) onward, until the next transition."""

    start_lap: int
    weather: WeatherState
    rain_probability: float = 0.0
    track_temperature_c: float | None = None
    air_temperature_c: float | None = None


@dataclass(frozen=True)
class PitStopEvent:
    """A literal, in-run pit stop: this LOCAL lap becomes the pit lap.

    Simplified model, documented rather than hidden: the stop is treated
    as happening at the START of the pit lap (real pit entry is partway
    through a lap) -- `stationary_time_s` of stopped time (speed 0,
    `pit_status=IN_PIT_BOX`) is inserted before the lap's normal distance
    is driven, and the REST of that lap (drive through/out of the pit
    lane) is speed-capped at `pit_lane_speed_kph`. Tyre age resets to 0 and
    compound changes to `new_compound` effective from the moment the
    stationary time ends -- i.e. for the pit-lane-speed portion of this
    lap and every lap after it, until another `PitStopEvent`.
    """

    lap: int
    new_compound: TyreCompound
    stationary_time_s: float = 2.5
    pit_lane_speed_kph: float = 80.0


@dataclass
class GeneratorConfig:
    car_id: str = "44"
    laps: int = 10
    compound: TyreCompound = TyreCompound.MEDIUM
    starting_fuel_kg: float = 110.0
    fuel_burn_per_lap_kg: float = 1.8
    tick_hz: float = 5.0
    v_max_kph: float = 330.0
    track: SyntheticTrack = field(default_factory=default_track)
    noise: NoiseConfig = field(default_factory=NoiseConfig.clean)
    starting_position: int = 5
    track_temperature_c: float = 38.0
    air_temperature_c: float = 27.0
    weather: WeatherState = WeatherState.DRY
    start_time: datetime = DEFAULT_START_TIME
    # First value of `frame.lap` this run produces. Distinct from tyre age,
    # which always starts at 0 -- this is what lets a second stint (fresh
    # tyres, but NOT a fresh race/track) be generated honestly: set
    # `starting_lap` to where the previous stint left off. Track evolution
    # is a track/session property and uses this global lap number; fuel and
    # degradation are stint-relative and don't. See
    # tests/test_tyre_model.py's multi-stint validation for why this
    # distinction matters -- faking a lap offset only at the fitting step,
    # without the underlying data reflecting it, produces biased,
    # internally-inconsistent validation data.
    starting_lap: int = 1
    flag_periods: tuple[FlagPeriod, ...] = ()
    weather_transitions: tuple[WeatherTransition, ...] = ()
    pit_stops: tuple[PitStopEvent, ...] = ()


def _gear_for_speed(speed_kph: float) -> int:
    gear = 1
    for i, threshold in enumerate(_GEAR_SPEED_THRESHOLDS_KPH):
        if speed_kph >= threshold:
            gear = i + 1
    return min(gear, 8)


def _corner_lateral_window(track: SyntheticTrack, distance_m: float):
    corner = track.corner_at(distance_m)
    if corner is None:
        return None, 0.0
    half = corner.arc_length_m / 2.0
    dist_from_apex = abs((distance_m - corner.apex_distance_m + track.length_m / 2) % track.length_m - track.length_m / 2)
    intensity = max(0.0, 1.0 - dist_from_apex / half) if half > 0 else 0.0
    return corner, intensity


def _active_flag_period(cfg: "GeneratorConfig", global_lap: int) -> FlagPeriod | None:
    for period in cfg.flag_periods:
        if period.start_lap <= global_lap <= period.end_lap:
            return period
    return None


def _active_weather(cfg: "GeneratorConfig", global_lap: int) -> WeatherTransition:
    applicable = [t for t in cfg.weather_transitions if t.start_lap <= global_lap]
    if not applicable:
        return WeatherTransition(start_lap=0, weather=cfg.weather, rain_probability=0.0 if cfg.weather == WeatherState.DRY else 0.6)
    return max(applicable, key=lambda t: t.start_lap)


class TelemetryGenerator:
    """Produces a deterministic telemetry sequence for one car's stint."""

    def __init__(self, config: GeneratorConfig, seed: int):
        self.config = config
        self.seed = seed
        self._rng = random.Random(seed)
        self._speed_profile = build_speed_profile(config.track, config.v_max_kph)
        self.injected_events: list[tuple[int, str]] = []

    def ground_truth_pace_penalty_s(
        self, lap: int, tyre_age_laps: int, fuel_load_kg: float, compound: TyreCompound | None = None
    ) -> float:
        """The total known pace penalty for a lap, for validation against estimators.

        `lap` is this run's stint-local lap (1-indexed from this
        generation's start). Track evolution additionally applies
        `config.starting_lap` to get the global race lap, since track
        evolution is a session/track property, not a stint-relative one --
        unlike degradation (tyre-relative) and fuel (stint-relative). With
        the default `starting_lap=1` this is a no-op (global == local).

        `compound` defaults to `config.compound` -- pass it explicitly for
        a lap after an in-run pit stop (`GeneratorConfig.pit_stops`), where
        the active compound has changed from the config's starting one.
        """

        active_compound = compound if compound is not None else self.config.compound
        degradation = COMPOUND_MODELS[active_compound].pace_penalty_s(tyre_age_laps)
        fuel = fuel_effect_s(fuel_load_kg)
        global_lap = self.config.starting_lap + lap - 1
        evolution = track_evolution_gain_s(global_lap)
        return degradation + fuel + evolution

    def frames(self) -> Iterator[RaceTelemetry]:
        cfg = self.config
        dt = 1.0 / cfg.tick_hz
        baseline_lap_time = self._speed_profile.lap_time_s()
        sequence_id = 0
        elapsed_s = 0.0
        prev_speed_ms = kph_to_ms(self._speed_profile.speed_kph_at(0.0))

        pit_stops_by_lap = {p.lap: p for p in cfg.pit_stops}
        current_compound = cfg.compound
        age_reference_lap = 1  # local lap at which the current tyre set was fitted
        pit_history: list[PitStop] = []

        for lap in range(1, cfg.laps + 1):
            pit_event = pit_stops_by_lap.get(lap)
            tyre_age_laps = lap - age_reference_lap
            global_lap = cfg.starting_lap + lap - 1
            pos_m = 0.0
            fuel_at_lap_start = max(cfg.starting_fuel_kg - cfg.fuel_burn_per_lap_kg * (lap - 1), 0.0)

            active_flag = _active_flag_period(cfg, global_lap)
            active_weather = _active_weather(cfg, global_lap)
            speed_cap_fraction = 1.0
            if active_flag is not None:
                if active_flag.speed_cap_fraction is not None:
                    speed_cap_fraction = active_flag.speed_cap_fraction
                elif active_flag.kind == "SC":
                    speed_cap_fraction = SC_SPEED_CAP_FRACTION
                else:
                    speed_cap_fraction = VSC_SPEED_CAP_FRACTION
            if pit_event is not None:
                speed_cap_fraction = min(speed_cap_fraction, pit_event.pit_lane_speed_kph / cfg.v_max_kph)

            if pit_event is not None:
                # Stationary phase: simplified as happening at the top of
                # the pit lap (see PitStopEvent's docstring). Speed 0,
                # position frozen, still on the OLD tyre until the moment
                # the stop ends.
                stationary_ticks = max(int(round(pit_event.stationary_time_s * cfg.tick_hz)), 1)
                entry_timestamp = cfg.start_time + timedelta(seconds=elapsed_s)
                for _ in range(stationary_ticks):
                    timestamp = cfg.start_time + timedelta(seconds=elapsed_s)
                    fuel_load = max(fuel_at_lap_start, 0.0)
                    thermal_base = cfg.track_temperature_c * 0.6 + cfg.air_temperature_c * 0.2 + 55.0
                    stationary_frame = RaceTelemetry(
                        source=DataSource.SIMULATOR,
                        source_timestamp=timestamp,
                        sequence_id=sequence_id,
                        car_id=cfg.car_id,
                        lap=global_lap,
                        sector=1,
                        position=cfg.starting_position,
                        speed_kph=0.0,
                        acceleration_ms2=0.0,
                        longitudinal_acceleration_g=0.0,
                        lateral_acceleration_g=0.0,
                        throttle_pct=0.0,
                        brake_pct=0.0,
                        steering_angle_deg=0.0,
                        gear=1,
                        rpm=4000.0,
                        wheel_speeds=WheelSpeeds(front_left=0.0, front_right=0.0, rear_left=0.0, rear_right=0.0),
                        tyre_compound=current_compound,
                        tyre_age_laps=tyre_age_laps,
                        tyre_temperature=TyreTemperatures(
                            front_left_c=thermal_base, front_right_c=thermal_base,
                            rear_left_c=thermal_base, rear_right_c=thermal_base,
                        ),
                        fuel_load_kg=fuel_load,
                        track_temperature_c=active_weather.track_temperature_c or cfg.track_temperature_c,
                        air_temperature_c=active_weather.air_temperature_c or cfg.air_temperature_c,
                        weather=active_weather.weather,
                        rain_probability=active_weather.rain_probability,
                        track_state=TrackState.GREEN,
                        pit_status=PitStatus.IN_PIT_BOX,
                    )
                    yield stationary_frame
                    elapsed_s += dt
                    sequence_id += 1

                exit_timestamp = cfg.start_time + timedelta(seconds=elapsed_s)
                pit_history.append(
                    PitStop(
                        lap=global_lap,
                        entry_timestamp=entry_timestamp,
                        exit_timestamp=exit_timestamp,
                        stationary_time_s=pit_event.stationary_time_s,
                        compound_before=current_compound,
                        compound_after=pit_event.new_compound,
                    )
                )
                current_compound = pit_event.new_compound
                age_reference_lap = lap
                tyre_age_laps = 0
                prev_speed_ms = 0.0

            # Computed AFTER any pit-stop swap above, so a lap with a stop
            # uses the NEW compound/age=0 for the driven (pit-lane-capped)
            # portion -- using the pre-stop tyre here would apply stale
            # degradation to a fresh tyre.
            penalty_s = self.ground_truth_pace_penalty_s(lap, tyre_age_laps, fuel_at_lap_start, current_compound)
            pace_multiplier = max((baseline_lap_time + penalty_s) / baseline_lap_time, 0.3)

            pit_status = PitStatus.EXITING_PIT if pit_event is not None else PitStatus.ON_TRACK

            while pos_m < cfg.track.length_m:
                fuel_load = max(
                    fuel_at_lap_start - cfg.fuel_burn_per_lap_kg * (pos_m / cfg.track.length_m), 0.0
                )
                raw_speed_kph = (self._speed_profile.speed_kph_at(pos_m) / pace_multiplier) * speed_cap_fraction
                speed_ms = kph_to_ms(raw_speed_kph)

                longitudinal_g = (speed_ms - prev_speed_ms) / dt / 9.81
                corner, intensity = _corner_lateral_window(cfg.track, pos_m)
                lateral_g = 0.0
                steering_deg = 0.0
                if corner is not None and intensity > 0:
                    mu_assumed = 1.6
                    lateral_g = mu_assumed * intensity
                    sharpness = max(5.0, 90.0 - corner.apex_speed_kph / 4.0)
                    steering_deg = corner.direction * sharpness * intensity

                if longitudinal_g > 0.05:
                    throttle_pct = min(100.0, 60.0 + longitudinal_g * 30.0)
                    brake_pct = 0.0
                elif longitudinal_g < -0.05:
                    throttle_pct = 0.0
                    brake_pct = min(100.0, abs(longitudinal_g) * 22.0)
                else:
                    throttle_pct = 40.0
                    brake_pct = 0.0

                gear = _gear_for_speed(raw_speed_kph)
                rpm = 4000.0 + (raw_speed_kph / cfg.v_max_kph) * 8000.0

                lateral_wheel_bias = 1.0 + (0.015 * lateral_g * (1 if corner and corner.direction > 0 else -1))
                wheel_speeds = WheelSpeeds(
                    front_left=raw_speed_kph * (2 - lateral_wheel_bias),
                    front_right=raw_speed_kph * lateral_wheel_bias,
                    rear_left=raw_speed_kph * (2 - lateral_wheel_bias) * 0.995,
                    rear_right=raw_speed_kph * lateral_wheel_bias * 0.995,
                )

                thermal_base = cfg.track_temperature_c * 0.6 + cfg.air_temperature_c * 0.2 + 55.0
                load_heat = lateral_g * 12.0 + abs(longitudinal_g) * 6.0
                age_heat = min(tyre_age_laps * 0.4, 8.0)
                tyre_temperature = TyreTemperatures(
                    front_left_c=thermal_base + load_heat + age_heat,
                    front_right_c=thermal_base + load_heat + age_heat,
                    rear_left_c=thermal_base + load_heat * 1.15 + age_heat,
                    rear_right_c=thermal_base + load_heat * 1.15 + age_heat,
                )

                sector = min(int(pos_m / (cfg.track.length_m / 3.0)) + 1, 3)
                timestamp = cfg.start_time + timedelta(seconds=elapsed_s)

                frame = RaceTelemetry(
                    source=DataSource.SIMULATOR,
                    source_timestamp=timestamp,
                    sequence_id=sequence_id,
                    car_id=cfg.car_id,
                    lap=global_lap,
                    sector=sector,
                    position=cfg.starting_position,
                    speed_kph=raw_speed_kph,
                    acceleration_ms2=longitudinal_g * 9.81,
                    longitudinal_acceleration_g=longitudinal_g,
                    lateral_acceleration_g=lateral_g,
                    throttle_pct=throttle_pct,
                    brake_pct=brake_pct,
                    steering_angle_deg=steering_deg,
                    gear=gear,
                    rpm=rpm,
                    wheel_speeds=wheel_speeds,
                    tyre_compound=current_compound,
                    tyre_age_laps=tyre_age_laps,
                    tyre_temperature=tyre_temperature,
                    fuel_load_kg=fuel_load,
                    track_temperature_c=active_weather.track_temperature_c or cfg.track_temperature_c,
                    air_temperature_c=active_weather.air_temperature_c or cfg.air_temperature_c,
                    weather=active_weather.weather,
                    rain_probability=active_weather.rain_probability,
                    track_state=(
                        TrackState.SAFETY_CAR if active_flag and active_flag.kind == "SC"
                        else TrackState.VIRTUAL_SAFETY_CAR if active_flag and active_flag.kind == "VSC"
                        else TrackState.GREEN
                    ),
                    safety_car=bool(active_flag and active_flag.kind == "SC"),
                    vsc=bool(active_flag and active_flag.kind == "VSC"),
                    pit_status=pit_status,
                    pit_history=list(pit_history),
                )

                noise_result = apply_noise(frame, self._rng, cfg.noise)
                if noise_result.injected:
                    for event in noise_result.injected:
                        self.injected_events.append((sequence_id, event))

                yield noise_result.frame

                prev_speed_ms = speed_ms
                pos_m += speed_ms * dt
                elapsed_s += dt
                sequence_id += 1
