"""Tests for the concrete Phase 2 adapters: simulator, replay, real-car placeholder."""

from __future__ import annotations

import pytest

from backend.adapters.real_car_adapter import RealCarAdapter
from backend.adapters.replay_adapter import ReplayAdapter, load_frames_jsonl, save_frames_jsonl
from backend.adapters.simulator_adapter import SimulatorAdapter
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import NoiseConfig


# --- SimulatorAdapter -------------------------------------------------------


@pytest.mark.asyncio
async def test_simulator_adapter_streams_frames_for_configured_car():
    config = GeneratorConfig(car_id="7", laps=1, noise=NoiseConfig.clean())
    adapter = SimulatorAdapter(config, seed=1)

    await adapter.connect()
    frames = [f async for f in adapter.stream()]
    await adapter.disconnect()

    assert len(frames) > 0
    assert all(f.car_id == "7" for f in frames)
    assert adapter.health().frames_received == len(frames)


@pytest.mark.asyncio
async def test_simulator_adapter_is_deterministic_given_same_seed():
    config = GeneratorConfig(laps=1, noise=NoiseConfig.moderate())

    adapter_a = SimulatorAdapter(config, seed=99)
    await adapter_a.connect()
    frames_a = [f async for f in adapter_a.stream()]

    adapter_b = SimulatorAdapter(config, seed=99)
    await adapter_b.connect()
    frames_b = [f async for f in adapter_b.stream()]

    assert len(frames_a) == len(frames_b)
    assert [f.speed_kph for f in frames_a] == [f.speed_kph for f in frames_b]
    assert [f.sequence_id for f in frames_a] == [f.sequence_id for f in frames_b]


@pytest.mark.asyncio
async def test_simulator_adapter_drops_packets_per_noise_config():
    config = GeneratorConfig(laps=1, noise=NoiseConfig(missing_packet_probability=0.5))
    raw_count = len(list(TelemetryGenerator(config, seed=5).frames()))

    adapter = SimulatorAdapter(config, seed=5)
    await adapter.connect()
    frames = [f async for f in adapter.stream()]

    assert len(frames) < raw_count
    assert adapter.health().frames_dropped > 0
    assert adapter.health().frames_dropped + adapter.health().frames_received >= raw_count


@pytest.mark.asyncio
async def test_simulator_adapter_duplicates_packets_per_noise_config():
    config = GeneratorConfig(laps=1, noise=NoiseConfig(duplicate_packet_probability=0.9))

    adapter = SimulatorAdapter(config, seed=5)
    await adapter.connect()
    frames = [f async for f in adapter.stream()]

    sequence_ids = [f.sequence_id for f in frames]
    assert len(sequence_ids) != len(set(sequence_ids))  # some sequence_id repeats


@pytest.mark.asyncio
async def test_simulator_adapter_raises_if_streamed_before_connect():
    config = GeneratorConfig(laps=1)
    adapter = SimulatorAdapter(config, seed=1)

    with pytest.raises(RuntimeError):
        async for _ in adapter.stream():
            pass


def test_simulator_adapter_replay_descriptor_is_stable_for_same_config():
    config = GeneratorConfig(laps=3, noise=NoiseConfig.moderate())

    d1 = SimulatorAdapter(config, seed=17, scenario_id="test_scenario").replay_descriptor()
    d2 = SimulatorAdapter(config, seed=17, scenario_id="test_scenario").replay_descriptor()

    assert d1.run_id == d2.run_id
    assert d1.scenario_id == "test_scenario"
    assert d1.seed == 17


# --- ReplayAdapter -----------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_adapter_streams_frames_from_memory_in_order():
    frames = list(TelemetryGenerator(GeneratorConfig(laps=1), seed=1).frames())[:10]

    adapter = ReplayAdapter(frames=frames, scenario_id="in_memory_test", seed=1)
    await adapter.connect()
    replayed = [f async for f in adapter.stream()]

    assert [f.sequence_id for f in replayed] == [f.sequence_id for f in frames]
    assert adapter.health().frames_received == 10


@pytest.mark.asyncio
async def test_replay_adapter_round_trips_through_jsonl(tmp_path):
    frames = list(TelemetryGenerator(GeneratorConfig(laps=1), seed=2).frames())[:5]
    file_path = tmp_path / "recorded.jsonl"
    save_frames_jsonl(frames, file_path)

    reloaded = load_frames_jsonl(file_path)
    assert len(reloaded) == 5
    assert reloaded[0].speed_kph == pytest.approx(frames[0].speed_kph)
    assert reloaded[0].source_timestamp == frames[0].source_timestamp

    adapter = ReplayAdapter(file_path=file_path, scenario_id="jsonl_test", seed=2)
    await adapter.connect()
    replayed = [f async for f in adapter.stream()]
    assert len(replayed) == 5


def test_replay_adapter_requires_exactly_one_source():
    with pytest.raises(ValueError):
        ReplayAdapter()
    with pytest.raises(ValueError):
        ReplayAdapter(frames=[], file_path="somewhere.jsonl")


# --- RealCarAdapter -----------------------------------------------------------


def test_real_car_adapter_conforms_to_interface_but_is_not_connected():
    adapter = RealCarAdapter()
    assert adapter.health().connected is False
    assert adapter.health().last_error is not None


@pytest.mark.asyncio
async def test_real_car_adapter_connect_raises_not_implemented():
    adapter = RealCarAdapter()
    with pytest.raises(NotImplementedError):
        await adapter.connect()


@pytest.mark.asyncio
async def test_real_car_adapter_stream_raises_not_implemented():
    adapter = RealCarAdapter()
    with pytest.raises(NotImplementedError):
        async for _ in adapter.stream():
            pass
