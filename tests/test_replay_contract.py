"""Tests for the deterministic-replay contract (backend/adapters/replay.py)."""

from __future__ import annotations

from backend.adapters.replay import ReplayCapable, ReplayDescriptor


def test_same_config_produces_same_hash_and_run_id():
    a = ReplayDescriptor(scenario_id="vsc_undercut", seed=18472, config={"laps": 50, "rain": False})
    b = ReplayDescriptor(scenario_id="vsc_undercut", seed=18472, config={"rain": False, "laps": 50})

    assert a.config_hash == b.config_hash
    assert a.run_id == b.run_id


def test_different_seed_produces_different_run_id():
    a = ReplayDescriptor(scenario_id="vsc_undercut", seed=1, config={"laps": 50})
    b = ReplayDescriptor(scenario_id="vsc_undercut", seed=2, config={"laps": 50})

    assert a.run_id != b.run_id
    assert a.config_hash == b.config_hash  # config itself is identical


def test_different_config_produces_different_hash():
    a = ReplayDescriptor(scenario_id="vsc_undercut", seed=1, config={"laps": 50})
    b = ReplayDescriptor(scenario_id="vsc_undercut", seed=1, config={"laps": 51})

    assert a.config_hash != b.config_hash


def test_to_dict_is_json_serializable():
    import json

    descriptor = ReplayDescriptor(scenario_id="rain_arrival", seed=7, config={"lap_of_rain": 20})
    serialized = json.dumps(descriptor.to_dict())
    assert "rain_arrival" in serialized


def test_replay_capable_is_a_runtime_checkable_protocol():
    class ReproducibleThing:
        def replay_descriptor(self) -> ReplayDescriptor:
            return ReplayDescriptor(scenario_id="normal_race", seed=1, config={})

    class NotReproducibleThing:
        pass

    assert isinstance(ReproducibleThing(), ReplayCapable)
    assert not isinstance(NotReproducibleThing(), ReplayCapable)
