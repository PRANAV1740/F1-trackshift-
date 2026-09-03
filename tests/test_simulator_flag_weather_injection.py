"""Tests for SC/VSC and weather injection in simulator/generator/core.py (Phase 12/13)."""

from __future__ import annotations

from backend.telemetry.schema import TrackState, WeatherState
from simulator.generator.core import (
    SC_SPEED_CAP_FRACTION,
    VSC_SPEED_CAP_FRACTION,
    FlagPeriod,
    GeneratorConfig,
    TelemetryGenerator,
    WeatherTransition,
)
from simulator.generator.noise import NoiseConfig


def test_no_flag_periods_means_all_green():
    config = GeneratorConfig(laps=2, noise=NoiseConfig.clean())
    frames = list(TelemetryGenerator(config, seed=1).frames())
    assert all(f.track_state == TrackState.GREEN and not f.safety_car and not f.vsc for f in frames)


def test_safety_car_period_sets_flags_and_slows_the_car():
    config = GeneratorConfig(laps=3, noise=NoiseConfig.clean(), flag_periods=(FlagPeriod(start_lap=2, end_lap=2, kind="SC"),))
    frames = list(TelemetryGenerator(config, seed=1).frames())

    lap1_speeds = [f.speed_kph for f in frames if f.lap == 1]
    lap2_speeds = [f.speed_kph for f in frames if f.lap == 2]
    lap3_speeds = [f.speed_kph for f in frames if f.lap == 3]

    assert all(f.track_state == TrackState.GREEN for f in frames if f.lap == 1)
    assert all(f.track_state == TrackState.SAFETY_CAR and f.safety_car and not f.vsc for f in frames if f.lap == 2)
    assert all(f.track_state == TrackState.GREEN for f in frames if f.lap == 3)

    assert max(lap2_speeds) < max(lap1_speeds) * (SC_SPEED_CAP_FRACTION + 0.1)
    assert max(lap3_speeds) > max(lap2_speeds)  # speed recovers after SC ends


def test_vsc_period_sets_flags_and_slows_less_than_sc():
    config = GeneratorConfig(
        laps=4, noise=NoiseConfig.clean(),
        flag_periods=(FlagPeriod(start_lap=2, end_lap=2, kind="VSC"), FlagPeriod(start_lap=3, end_lap=3, kind="SC")),
    )
    frames = list(TelemetryGenerator(config, seed=1).frames())

    vsc_speeds = [f.speed_kph for f in frames if f.lap == 2]
    sc_speeds = [f.speed_kph for f in frames if f.lap == 3]

    assert all(f.vsc and not f.safety_car for f in frames if f.lap == 2)
    assert all(f.safety_car and not f.vsc for f in frames if f.lap == 3)
    assert max(vsc_speeds) > max(sc_speeds)  # VSC is faster than full SC


def test_weather_transition_changes_weather_and_rain_probability_from_start_lap():
    config = GeneratorConfig(
        laps=3, noise=NoiseConfig.clean(),
        weather_transitions=(WeatherTransition(start_lap=2, weather=WeatherState.WET, rain_probability=0.9),),
    )
    frames = list(TelemetryGenerator(config, seed=1).frames())

    assert all(f.weather == WeatherState.DRY for f in frames if f.lap == 1)
    assert all(f.weather == WeatherState.WET and f.rain_probability == 0.9 for f in frames if f.lap == 2)


def test_flag_and_weather_injection_is_deterministic():
    config = GeneratorConfig(
        laps=3, noise=NoiseConfig.moderate(),
        flag_periods=(FlagPeriod(2, 2, "SC"),),
        weather_transitions=(WeatherTransition(2, WeatherState.DAMP, 0.4),),
    )
    a = list(TelemetryGenerator(config, seed=5).frames())
    b = list(TelemetryGenerator(config, seed=5).frames())
    assert [f.speed_kph for f in a] == [f.speed_kph for f in b]
    assert [f.safety_car for f in a] == [f.safety_car for f in b]
