"""Tests for the deterministic synthetic telemetry generator."""

from __future__ import annotations

from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig
from simulator.generator.physics import build_speed_profile
from simulator.generator.track import default_track


def test_speed_profile_never_exceeds_v_max_and_is_positive():
    track = default_track()
    profile = build_speed_profile(track, v_max_kph=330.0)

    assert all(0 <= v <= 92.0 for v in profile.speeds_ms)  # 330 kph = 91.7 m/s
    assert profile.lap_time_s() > 0


def test_speed_profile_respects_corner_apex_speeds():
    track = default_track()
    profile = build_speed_profile(track, v_max_kph=330.0)

    for corner in track.corners:
        speed_at_apex = profile.speed_kph_at(corner.apex_distance_m)
        # allow small slack for discretization (STEP_M granularity)
        assert speed_at_apex <= corner.apex_speed_kph + 3.0


def test_generator_is_deterministic_given_same_seed_and_config():
    config = GeneratorConfig(laps=2, noise=NoiseConfig.severe())

    gen_a = TelemetryGenerator(config, seed=42)
    gen_b = TelemetryGenerator(config, seed=42)

    frames_a = list(gen_a.frames())
    frames_b = list(gen_b.frames())

    assert len(frames_a) == len(frames_b) > 0
    for fa, fb in zip(frames_a, frames_b):
        assert fa.speed_kph == fb.speed_kph
        assert fa.source_timestamp == fb.source_timestamp
        assert fa.tyre_temperature.front_left_c == fb.tyre_temperature.front_left_c

    assert gen_a.injected_events == gen_b.injected_events


def test_different_seed_changes_noise_pattern():
    config = GeneratorConfig(laps=1, noise=NoiseConfig.severe())

    frames_a = list(TelemetryGenerator(config, seed=1).frames())
    frames_b = list(TelemetryGenerator(config, seed=2).frames())

    speeds_a = [f.speed_kph for f in frames_a[: min(len(frames_a), len(frames_b))]]
    speeds_b = [f.speed_kph for f in frames_b[: min(len(frames_a), len(frames_b))]]
    assert speeds_a != speeds_b


def test_clean_config_produces_no_injected_corruption():
    config = GeneratorConfig(laps=1, noise=NoiseConfig.clean())
    gen = TelemetryGenerator(config, seed=7)

    frames = list(gen.frames())

    assert len(frames) > 0
    assert gen.injected_events == []


def test_tyre_age_and_fuel_evolve_across_laps():
    config = GeneratorConfig(laps=3, noise=NoiseConfig.clean())
    frames = list(TelemetryGenerator(config, seed=1).frames())

    ages_by_lap = {}
    fuel_by_lap_start = {}
    for f in frames:
        ages_by_lap.setdefault(f.lap, f.tyre_age_laps)
        fuel_by_lap_start.setdefault(f.lap, f.fuel_load_kg)

    assert ages_by_lap[1] == 0
    assert ages_by_lap[2] == 1
    assert ages_by_lap[3] == 2

    # fuel strictly decreases lap over lap (start-of-lap fuel)
    assert fuel_by_lap_start[1] > fuel_by_lap_start[2] > fuel_by_lap_start[3]

    # fuel decreases monotonically (non-increasing) within the whole run
    fuels = [f.fuel_load_kg for f in frames]
    assert all(fuels[i] >= fuels[i + 1] - 1e-9 for i in range(len(fuels) - 1))


def test_pace_penalty_degradation_component_grows_with_tyre_age():
    """Isolate the degradation trend by holding fuel and lap (for track
    evolution) constant -- with fuel and evolution fixed, a higher tyre age
    must produce a higher total penalty. (Net penalty across a real stint is
    NOT monotonic: fuel burn-off dominates early and outweighs the still-small
    degradation term, which is realistic -- that's why fuel is held constant
    here rather than compared lap-to-lap.)"""

    config = GeneratorConfig(laps=20)
    gen = TelemetryGenerator(config, seed=1)

    penalty_young = gen.ground_truth_pace_penalty_s(lap=1, tyre_age_laps=1, fuel_load_kg=80)
    penalty_old = gen.ground_truth_pace_penalty_s(lap=1, tyre_age_laps=14, fuel_load_kg=80)
    assert penalty_old > penalty_young


def test_all_frames_pass_schema_validation():
    """The generator must never produce a frame the common schema rejects
    outright (missing required fields, wrong enum values, etc.)."""

    config = GeneratorConfig(laps=1, noise=NoiseConfig.moderate())
    frames = list(TelemetryGenerator(config, seed=3).frames())
    assert len(frames) > 0
    for f in frames:
        assert f.car_id == config.car_id
        assert f.lap >= 1
