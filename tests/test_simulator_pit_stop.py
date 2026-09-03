"""Tests for the literal in-run pit stop capability (Phase 18 core gap,
simulator/generator/core.py::PitStopEvent).
"""

from __future__ import annotations

from backend.telemetry.schema import PitStatus, TyreCompound
from simulator.generator.core import GeneratorConfig, PitStopEvent, TelemetryGenerator
from simulator.generator.noise import NoiseConfig


def test_pit_stop_produces_a_stationary_phase_with_zero_speed():
    config = GeneratorConfig(
        laps=3, compound=TyreCompound.MEDIUM, noise=NoiseConfig.clean(),
        pit_stops=(PitStopEvent(lap=2, new_compound=TyreCompound.HARD, stationary_time_s=2.5),),
    )
    frames = list(TelemetryGenerator(config, seed=1).frames())

    lap2_frames = [f for f in frames if f.lap == 2]
    stationary = [f for f in lap2_frames if f.pit_status == PitStatus.IN_PIT_BOX]

    assert len(stationary) > 0
    assert all(f.speed_kph == 0.0 for f in stationary)
    # roughly stationary_time_s worth of ticks at the configured tick_hz
    expected_ticks = round(2.5 * config.tick_hz)
    assert abs(len(stationary) - expected_ticks) <= 1


def test_tyre_compound_and_age_reset_after_pit_stop():
    config = GeneratorConfig(
        laps=3, compound=TyreCompound.MEDIUM, noise=NoiseConfig.clean(),
        pit_stops=(PitStopEvent(lap=2, new_compound=TyreCompound.HARD),),
    )
    frames = list(TelemetryGenerator(config, seed=1).frames())

    lap1_frames = [f for f in frames if f.lap == 1]
    lap2_driven = [f for f in frames if f.lap == 2 and f.pit_status != PitStatus.IN_PIT_BOX]
    lap3_frames = [f for f in frames if f.lap == 3]

    assert all(f.tyre_compound == TyreCompound.MEDIUM for f in lap1_frames)
    assert all(f.tyre_compound == TyreCompound.HARD for f in lap2_driven)
    assert all(f.tyre_age_laps == 0 for f in lap2_driven)
    assert all(f.tyre_compound == TyreCompound.HARD for f in lap3_frames)
    assert all(f.tyre_age_laps == 1 for f in lap3_frames)


def test_pit_history_is_recorded_and_carried_forward():
    config = GeneratorConfig(
        laps=3, compound=TyreCompound.SOFT, noise=NoiseConfig.clean(),
        pit_stops=(PitStopEvent(lap=2, new_compound=TyreCompound.HARD, stationary_time_s=3.0),),
    )
    frames = list(TelemetryGenerator(config, seed=1).frames())

    before_stop = [f for f in frames if f.lap == 1]
    after_stop = [f for f in frames if f.lap == 3]

    assert all(len(f.pit_history) == 0 for f in before_stop)
    assert all(len(f.pit_history) == 1 for f in after_stop)
    stop = after_stop[0].pit_history[0]
    assert stop.compound_before == TyreCompound.SOFT
    assert stop.compound_after == TyreCompound.HARD
    assert stop.stationary_time_s == 3.0
    assert stop.exit_timestamp > stop.entry_timestamp


def test_driven_portion_of_pit_lap_is_speed_capped():
    config = GeneratorConfig(
        laps=2, compound=TyreCompound.MEDIUM, noise=NoiseConfig.clean(), v_max_kph=330.0,
        pit_stops=(PitStopEvent(lap=1, new_compound=TyreCompound.HARD, pit_lane_speed_kph=80.0),),
    )
    frames = list(TelemetryGenerator(config, seed=1).frames())

    driven_pit_lap = [f for f in frames if f.lap == 1 and f.pit_status == PitStatus.EXITING_PIT]
    assert len(driven_pit_lap) > 0
    assert max(f.speed_kph for f in driven_pit_lap) <= 80.5  # small slack for float rounding


def test_normal_laps_have_on_track_pit_status_and_empty_history_without_stops():
    config = GeneratorConfig(laps=2, noise=NoiseConfig.clean())
    frames = list(TelemetryGenerator(config, seed=1).frames())
    assert all(f.pit_status == PitStatus.ON_TRACK for f in frames)
    assert all(f.pit_history == [] for f in frames)


def test_multiple_pit_stops_in_one_run():
    config = GeneratorConfig(
        laps=5, compound=TyreCompound.SOFT, noise=NoiseConfig.clean(),
        pit_stops=(
            PitStopEvent(lap=2, new_compound=TyreCompound.MEDIUM),
            PitStopEvent(lap=4, new_compound=TyreCompound.HARD),
        ),
    )
    frames = list(TelemetryGenerator(config, seed=1).frames())

    lap5_frames = [f for f in frames if f.lap == 5]
    assert all(f.tyre_compound == TyreCompound.HARD for f in lap5_frames)
    assert all(f.tyre_age_laps == 1 for f in lap5_frames)
    assert all(len(f.pit_history) == 2 for f in lap5_frames)


def test_pit_stop_run_is_still_deterministic():
    config = GeneratorConfig(
        laps=3, noise=NoiseConfig.moderate(),
        pit_stops=(PitStopEvent(lap=2, new_compound=TyreCompound.HARD),),
    )
    a = list(TelemetryGenerator(config, seed=9).frames())
    b = list(TelemetryGenerator(config, seed=9).frames())
    assert [f.speed_kph for f in a] == [f.speed_kph for f in b]
    assert [f.pit_status for f in a] == [f.pit_status for f in b]


def test_pit_stop_pipeline_integration_excludes_pit_lap_from_tyre_fitting():
    from backend.normalization.stages import default_pipeline
    from backend.state.estimator import RaceStateEstimator
    from backend.tyre.estimator import TyreDegradationEstimator

    config = GeneratorConfig(
        laps=4, compound=TyreCompound.MEDIUM, noise=NoiseConfig.clean(),
        pit_stops=(PitStopEvent(lap=2, new_compound=TyreCompound.HARD, stationary_time_s=2.5),),
    )
    frames = list(TelemetryGenerator(config, seed=1).frames())

    pipeline = default_pipeline()
    race_state_estimator = RaceStateEstimator()
    tyre_estimator = TyreDegradationEstimator()

    for frame in frames:
        result = pipeline.process(frame)
        state = race_state_estimator.update(result)
        if state is not None:
            tyre_estimator.update(state)

    final_state = race_state_estimator.get_state(config.car_id)
    assert final_state is not None
    assert len(final_state.completed_laps) == 3

    # Lap 2 was the pit lap
    lap2 = [l for l in final_state.completed_laps if l.lap == 2][0]
    assert lap2.was_pit_lap is True

    # Non-pit laps should have was_pit_lap == False
    lap1 = [l for l in final_state.completed_laps if l.lap == 1][0]
    lap3 = [l for l in final_state.completed_laps if l.lap == 3][0]
    assert lap1.was_pit_lap is False
    assert lap3.was_pit_lap is False

    # Check that lap 2 is NOT in tyre_estimator's observations for (car_id, TyreCompound.MEDIUM)
    medium_obs = tyre_estimator._observations[(config.car_id, TyreCompound.MEDIUM)]
    medium_observed_laps = [obs.lap for obs in medium_obs]
    assert 2 not in medium_observed_laps
    assert 1 in medium_observed_laps

