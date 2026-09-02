"""Integration tests for backend/ingestion/service.py.

Exercises the full adapter -> validation -> normalization -> event bus /
sinks path, including the error-isolation guarantees: a malformed frame, a
failing adapter, and a failing sink must each be logged and counted without
taking down ingestion for everything else.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import pytest

from backend.adapters.base import AdapterHealth, SourceAdapter
from backend.adapters.simulator_adapter import SimulatorAdapter
from backend.ingestion.service import IngestionService
from backend.normalization.base import NormalizationPipeline, NormalizationResult, NormalizationStage
from backend.telemetry.schema import DataSource, RaceTelemetry
from simulator.generator.core import GeneratorConfig
from simulator.generator.noise import NoiseConfig


class PassThroughStage(NormalizationStage):
    name = "pass_through"

    def process(self, frame, context, log):
        return frame


def _pipeline() -> NormalizationPipeline:
    return NormalizationPipeline([PassThroughStage()])


class FiniteFakeAdapter(SourceAdapter):
    """Yields a fixed, hand-built list of frames then stops -- used to inject
    specific malformed/well-formed frames without going through the simulator."""

    source_type = DataSource.SIMULATOR

    def __init__(self, frames: list, raise_after: int | None = None):
        self._frames = frames
        self._raise_after = raise_after
        self._health = AdapterHealth(connected=False, source=self.source_type)

    async def connect(self) -> None:
        self._health.connected = True

    async def disconnect(self) -> None:
        self._health.connected = False

    def health(self) -> AdapterHealth:
        return self._health

    async def stream(self) -> AsyncIterator[RaceTelemetry]:
        for i, frame in enumerate(self._frames):
            if self._raise_after is not None and i == self._raise_after:
                raise RuntimeError("simulated adapter failure")
            yield frame


def _frame(**overrides) -> RaceTelemetry:
    defaults = dict(
        source=DataSource.SIMULATOR,
        source_timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        car_id="44",
        lap=1,
    )
    defaults.update(overrides)
    return RaceTelemetry(**defaults)


@pytest.mark.asyncio
async def test_ingestion_processes_frames_from_simulator_adapter():
    config = GeneratorConfig(laps=1, noise=NoiseConfig.clean())
    adapter = SimulatorAdapter(config, seed=1)
    collected: list[NormalizationResult] = []

    service = IngestionService(adapters=[adapter], pipeline=_pipeline(), sinks=[collected.append])
    await service.run()

    assert service.metrics.frames_ingested > 0
    assert len(collected) == service.metrics.frames_ingested
    assert all(r.normalized_frame is not None for r in collected)


@pytest.mark.asyncio
async def test_ingestion_attaches_ingest_timestamp():
    frames = [_frame(sequence_id=1)]
    adapter = FiniteFakeAdapter(frames)
    collected: list[NormalizationResult] = []

    service = IngestionService(adapters=[adapter], pipeline=_pipeline(), sinks=[collected.append])
    await service.run()

    assert collected[0].normalized_frame.ingest_timestamp is not None


@pytest.mark.asyncio
async def test_ingestion_drops_and_counts_malformed_frames_without_crashing():
    good = _frame(sequence_id=1, car_id="44")
    malformed = _frame(sequence_id=2, car_id="   ")  # whitespace-only car_id
    good2 = _frame(sequence_id=3, car_id="44")

    adapter = FiniteFakeAdapter([good, malformed, good2])
    collected: list[NormalizationResult] = []

    service = IngestionService(adapters=[adapter], pipeline=_pipeline(), sinks=[collected.append])
    await service.run()

    assert service.metrics.frames_malformed == 1
    assert service.metrics.frames_ingested == 2
    assert len(collected) == 2


@pytest.mark.asyncio
async def test_ingestion_survives_one_adapter_failing():
    """One adapter raising mid-stream must not stop other adapters' frames
    from being processed, and must be counted rather than crashing the service."""

    good_adapter = FiniteFakeAdapter([_frame(sequence_id=1), _frame(sequence_id=2)])
    failing_adapter = FiniteFakeAdapter([_frame(sequence_id=10), _frame(sequence_id=11)], raise_after=1)

    collected: list[NormalizationResult] = []
    service = IngestionService(adapters=[good_adapter, failing_adapter], pipeline=_pipeline(), sinks=[collected.append])
    await service.run()

    assert service.metrics.adapter_errors == 1
    # the good adapter's 2 frames + the failing adapter's 1 frame before it raised
    assert service.metrics.frames_ingested == 3


@pytest.mark.asyncio
async def test_ingestion_survives_a_failing_sink():
    def broken_sink(result):
        raise RuntimeError("sink is broken")

    collected: list[NormalizationResult] = []
    frames = [_frame(sequence_id=1), _frame(sequence_id=2)]
    adapter = FiniteFakeAdapter(frames)

    service = IngestionService(
        adapters=[adapter], pipeline=_pipeline(), sinks=[broken_sink, collected.append]
    )
    await service.run()

    assert service.metrics.sink_errors == 2  # broken_sink fails for both frames
    assert len(collected) == 2  # the second (working) sink still ran both times


@pytest.mark.asyncio
async def test_ingestion_publishes_events_to_the_event_bus():
    frames = [_frame(sequence_id=1)]
    adapter = FiniteFakeAdapter(frames)

    service = IngestionService(adapters=[adapter], pipeline=_pipeline())
    queue = service.event_bus.subscribe()
    await service.run()

    assert not queue.empty()
    event = queue.get_nowait()
    assert event.car_id == "44"
    assert event.result.normalized_frame is not None


@pytest.mark.asyncio
async def test_ingestion_metrics_snapshot_is_serializable_shape():
    config = GeneratorConfig(laps=1, noise=NoiseConfig.clean())
    adapter = SimulatorAdapter(config, seed=1)

    service = IngestionService(adapters=[adapter], pipeline=_pipeline())
    await service.run()

    snapshot = service.metrics.snapshot()
    assert snapshot["frames_ingested"] > 0
    assert isinstance(snapshot["adapters"], dict)
    assert len(snapshot["adapters"]) == 1
