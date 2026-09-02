"""Configurable telemetry noise/corruption injection.

This is what makes generated telemetry a realistic test of the
normalization pipeline (Phase 3) rather than a clean-room fixture. All
randomness here is driven by a caller-supplied `random.Random(seed)`, never
the global RNG, so a `(seed, config)` pair always produces the same
corruption pattern -- required by the deterministic-replay contract
(backend/adapters/replay.py).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from backend.telemetry.schema import RaceTelemetry


@dataclass
class NoiseConfig:
    """All-zero/off by default -- a generator with a default config produces clean data."""

    speed_noise_std_kph: float = 0.0
    steering_noise_std_deg: float = 0.0
    brake_noise_std_pct: float = 0.0
    throttle_noise_std_pct: float = 0.0
    temperature_noise_std_c: float = 0.0
    timestamp_jitter_std_s: float = 0.0

    missing_packet_probability: float = 0.0
    spike_probability: float = 0.0
    spike_magnitude_multiplier: float = 4.0
    delayed_packet_probability: float = 0.0
    delayed_packet_delay_s: float = 2.0
    duplicate_packet_probability: float = 0.0

    @staticmethod
    def clean() -> "NoiseConfig":
        return NoiseConfig()

    @staticmethod
    def moderate() -> "NoiseConfig":
        return NoiseConfig(
            speed_noise_std_kph=1.5,
            steering_noise_std_deg=0.8,
            brake_noise_std_pct=1.5,
            throttle_noise_std_pct=1.5,
            temperature_noise_std_c=1.0,
            timestamp_jitter_std_s=0.03,
            missing_packet_probability=0.01,
            spike_probability=0.005,
            delayed_packet_probability=0.01,
            duplicate_packet_probability=0.005,
        )

    @staticmethod
    def severe() -> "NoiseConfig":
        return NoiseConfig(
            speed_noise_std_kph=6.0,
            steering_noise_std_deg=3.0,
            brake_noise_std_pct=5.0,
            throttle_noise_std_pct=5.0,
            temperature_noise_std_c=4.0,
            timestamp_jitter_std_s=0.15,
            missing_packet_probability=0.06,
            spike_probability=0.03,
            spike_magnitude_multiplier=6.0,
            delayed_packet_probability=0.05,
            delayed_packet_delay_s=3.0,
            duplicate_packet_probability=0.03,
        )


class PacketFate(str, Enum):
    NORMAL = "NORMAL"
    DROPPED = "DROPPED"
    DELAYED = "DELAYED"
    DUPLICATED = "DUPLICATED"


@dataclass
class PacketDecision:
    fate: PacketFate
    delay_s: float = 0.0


def decide_packet_fate(rng: random.Random, config: NoiseConfig) -> PacketDecision:
    """Roll once per packet to decide its transport fate.

    Checked in a fixed order so the same rng draws the same number of
    random values regardless of config, keeping determinism simple to
    reason about: one `rng.random()` call decides the outcome bucket.
    """

    roll = rng.random()
    cumulative = config.missing_packet_probability
    if roll < cumulative:
        return PacketDecision(PacketFate.DROPPED)
    cumulative += config.delayed_packet_probability
    if roll < cumulative:
        return PacketDecision(PacketFate.DELAYED, delay_s=config.delayed_packet_delay_s)
    cumulative += config.duplicate_packet_probability
    if roll < cumulative:
        return PacketDecision(PacketFate.DUPLICATED)
    return PacketDecision(PacketFate.NORMAL)


def _jitter(rng: random.Random, value: float | None, std: float, spike: bool, spike_mult: float) -> float | None:
    if value is None or std <= 0:
        return value
    noisy = value + rng.gauss(0.0, std)
    if spike:
        noisy += rng.choice([-1, 1]) * std * spike_mult
    return noisy


@dataclass
class NoiseResult:
    """The noisy frame plus what was actually injected, for ground-truth comparison.

    `injected` is deliberately NOT written onto `RaceTelemetry.data_quality_flags`
    -- that field is reserved for the normalization pipeline's own findings
    (see backend/telemetry/schema.py), and a raw frame must look like
    something a real source could have produced. Injected-corruption ground
    truth is a simulator-only side channel, used by simulator/generator
    tests and Phase 3's noise-handling validation to check how much of what
    was injected the pipeline actually catches.
    """

    frame: RaceTelemetry
    injected: list[str]


def apply_noise(frame: RaceTelemetry, rng: random.Random, config: NoiseConfig) -> NoiseResult:
    """Return a new frame with noise applied. Never mutates the input."""

    spike = rng.random() < config.spike_probability
    spike_field = rng.choice(["speed", "tyre_temp", "brake"]) if spike else None
    injected: list[str] = [f"SPIKE:{spike_field}"] if spike else []

    updates: dict = {}

    updates["speed_kph"] = _jitter(
        rng, frame.speed_kph, config.speed_noise_std_kph, spike_field == "speed", config.spike_magnitude_multiplier
    )
    updates["steering_angle_deg"] = _jitter(
        rng, frame.steering_angle_deg, config.steering_noise_std_deg, False, 1.0
    )
    if frame.brake_pct is not None:
        updates["brake_pct"] = _jitter(
            rng, frame.brake_pct, config.brake_noise_std_pct, spike_field == "brake", config.spike_magnitude_multiplier
        )
    if frame.throttle_pct is not None:
        updates["throttle_pct"] = _jitter(rng, frame.throttle_pct, config.throttle_noise_std_pct, False, 1.0)

    tt = frame.tyre_temperature
    tt_updates = {}
    for corner_field in ("front_left_c", "front_right_c", "rear_left_c", "rear_right_c"):
        val = getattr(tt, corner_field)
        tt_updates[corner_field] = _jitter(
            rng, val, config.temperature_noise_std_c, spike_field == "tyre_temp", config.spike_magnitude_multiplier
        )
    updates["tyre_temperature"] = tt.model_copy(update=tt_updates)

    if config.timestamp_jitter_std_s > 0:
        from datetime import timedelta

        jitter_s = rng.gauss(0.0, config.timestamp_jitter_std_s)
        updates["source_timestamp"] = frame.source_timestamp + timedelta(seconds=jitter_s)

    return NoiseResult(frame=frame.model_copy(update=updates), injected=injected)
