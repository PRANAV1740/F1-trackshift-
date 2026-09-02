"""Wraps `simulator/generator` behind the `SourceAdapter` contract.

Production code depends only on `SourceAdapter` -- this is the one place
that imports `simulator.generator`, so nothing downstream needs to know a
simulator exists at all (see docs/ARCHITECTURE.md's simulator-independence
principle).

Content-level sensor noise (speed/steering/temperature jitter, spikes) is
applied inside the generator, since it represents instrument noise.
Transport-level corruption -- dropped, delayed, duplicated packets -- is
applied here, since that's a property of the telemetry *link*, not the
sensors, and a real telemetry-link adapter would have exactly this same
concern.
"""

from __future__ import annotations

import asyncio
import dataclasses
import random
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from backend.adapters.base import AdapterHealth, SourceAdapter
from backend.adapters.replay import ReplayDescriptor
from backend.observability.logging import get_logger
from backend.telemetry.schema import DataSource, RaceTelemetry
from simulator.generator.core import GeneratorConfig, TelemetryGenerator
from simulator.generator.noise import PacketFate, decide_packet_fate

log = get_logger("adapters.simulator")


class SimulatorAdapter(SourceAdapter):
    """Streams deterministic synthetic telemetry for one car.

    `realtime=False` (the default) yields frames as fast as they can be
    produced -- what tests and batch evaluation want. `realtime=True`
    paces delivery to (simulated-time / speed_multiplier), for a live demo.
    """

    source_type = DataSource.SIMULATOR

    def __init__(
        self,
        config: GeneratorConfig,
        seed: int,
        scenario_id: str = "simulator_stint",
        realtime: bool = False,
        speed_multiplier: float = 1.0,
    ):
        self._config = config
        self._seed = seed
        self._scenario_id = scenario_id
        self._realtime = realtime
        self._speed_multiplier = max(speed_multiplier, 0.001)
        self._transport_rng = random.Random(seed ^ 0xA5A5A5)
        self._health = AdapterHealth(connected=False, source=self.source_type)

    async def connect(self) -> None:
        self._health.connected = True
        log.info("simulator adapter connected", extra={"fields": {"seed": self._seed, "car_id": self._config.car_id}})

    async def disconnect(self) -> None:
        self._health.connected = False
        log.info("simulator adapter disconnected", extra={"fields": {"seed": self._seed}})

    def health(self) -> AdapterHealth:
        return self._health

    def replay_descriptor(self) -> ReplayDescriptor:
        cfg = self._config
        config_dict = {
            "car_id": cfg.car_id,
            "laps": cfg.laps,
            "compound": cfg.compound.value,
            "starting_fuel_kg": cfg.starting_fuel_kg,
            "fuel_burn_per_lap_kg": cfg.fuel_burn_per_lap_kg,
            "tick_hz": cfg.tick_hz,
            "v_max_kph": cfg.v_max_kph,
            "track_name": cfg.track.name,
            "weather": cfg.weather.value,
            "noise": dataclasses.asdict(cfg.noise),
        }
        return ReplayDescriptor(scenario_id=self._scenario_id, seed=self._seed, config=config_dict)

    async def stream(self) -> AsyncIterator[RaceTelemetry]:
        if not self._health.connected:
            raise RuntimeError("SimulatorAdapter.stream() called before connect()")

        # Determinism requires a fixed simulated-time anchor (see
        # GeneratorConfig.start_time) so the same seed always reproduces the
        # same values. That fixed anchor is deliberately NOT real wall-clock
        # time, so comparing it against a real `ingest_timestamp` would
        # produce a meaningless multi-month "latency". In realtime mode we
        # re-anchor to actual now() -- pacing is still driven by the
        # generator's simulated dt between frames, so relative timing (and
        # therefore all noise/physics) stays exactly what the seed produces,
        # but the absolute timestamps become comparable to wall-clock time
        # for latency measurement. Batch/test mode keeps the fixed anchor,
        # where absolute latency-vs-now isn't a meaningful concept anyway.
        effective_config = self._config
        if self._realtime:
            effective_config = dataclasses.replace(self._config, start_time=datetime.now(timezone.utc))

        generator = TelemetryGenerator(effective_config, self._seed)
        last_source_ts: Optional[object] = None

        for frame in generator.frames():
            decision = decide_packet_fate(self._transport_rng, self._config.noise)

            if self._realtime and last_source_ts is not None:
                delta_s = (frame.source_timestamp - last_source_ts).total_seconds()
                if delta_s > 0:
                    await asyncio.sleep(delta_s / self._speed_multiplier)
            last_source_ts = frame.source_timestamp

            if decision.fate == PacketFate.DROPPED:
                self._health.frames_dropped += 1
                continue

            if decision.fate == PacketFate.DELAYED:
                pace = self._speed_multiplier if self._realtime else 1.0
                await asyncio.sleep(decision.delay_s / pace if self._realtime else 0)

            self._health.frames_received += 1
            self._health.last_frame_timestamp = frame.source_timestamp.isoformat()
            yield frame

            if decision.fate == PacketFate.DUPLICATED:
                self._health.frames_received += 1
                yield frame
