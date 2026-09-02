"""The telemetry ingestion service.

Owns adapter lifecycles, runs each adapter's stream concurrently, attaches
ingest timestamps, performs structural validation (distinct from the
normalization pipeline's *value*-plausibility validation -- see the module
docstring split in backend/normalization/base.py and
docs/ARCHITECTURE.md), pushes every structurally-valid frame through
normalization, and fans the result out to an `EventBus` plus any number of
"sinks" (Phase 4's race-state updater plugs in here as just another sink;
none is required today).

Error isolation, per engineering rule 18 ("never silently swallow
errors") and rule about optional subsystems not taking down the core
pipeline:

  * A structurally invalid frame is logged and counted, not raised --
    malformed/dropped/delayed telemetry is normal for a real-time system,
    not an exceptional condition (see Phase 2 requirements).
  * An adapter whose `stream()` raises has that failure logged with full
    context; that adapter's task ends, but every other adapter keeps
    running -- one dead telemetry link must not take the whole service down.
  * A sink that raises has that failure logged and counted; ingestion
    continues to the next frame. Sinks are downstream consumers ingestion
    does not control the correctness of, so a bug in one must not stop
    telemetry from reaching the others.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, Union

from backend.adapters.base import AdapterHealth, SourceAdapter
from backend.ingestion.bus import EventBus, IngestionEvent
from backend.normalization.base import NormalizationPipeline, NormalizationResult
from backend.observability.logging import get_logger
from backend.telemetry.schema import RaceTelemetry

log = get_logger("ingestion.service")

FrameSink = Callable[[NormalizationResult], Union[None, Awaitable[None]]]


class MalformedFrameError(ValueError):
    """Raised internally when a frame fails structural validation."""


@dataclass
class IngestionMetrics:
    frames_ingested: int = 0
    frames_malformed: int = 0
    adapter_errors: int = 0
    sink_errors: int = 0
    adapter_health: dict[str, AdapterHealth] = field(default_factory=dict)

    def snapshot(self) -> dict:
        return {
            "frames_ingested": self.frames_ingested,
            "frames_malformed": self.frames_malformed,
            "adapter_errors": self.adapter_errors,
            "sink_errors": self.sink_errors,
            "adapters": {
                name: {
                    "connected": h.connected,
                    "frames_received": h.frames_received,
                    "frames_dropped": h.frames_dropped,
                    "last_frame_timestamp": h.last_frame_timestamp,
                    "last_error": h.last_error,
                }
                for name, h in self.adapter_health.items()
            },
        }


def validate_structure(frame: RaceTelemetry) -> None:
    """Structural/identity validation only -- NOT physical-plausibility
    validation (that's the normalization pipeline's job; see the schema's
    deliberate-permissiveness design note in backend/telemetry/schema.py).
    A message ingestion cannot even attribute to a car cannot be routed
    anywhere downstream, which is a different kind of problem than a noisy
    sensor reading.
    """

    if not isinstance(frame, RaceTelemetry):
        raise MalformedFrameError(f"expected RaceTelemetry, got {type(frame)!r}")
    if not frame.car_id or not frame.car_id.strip():
        raise MalformedFrameError("car_id is empty")


class IngestionService:
    def __init__(
        self,
        adapters: list[SourceAdapter],
        pipeline: NormalizationPipeline,
        sinks: Optional[list[FrameSink]] = None,
        event_bus: Optional[EventBus] = None,
    ):
        self._adapters = adapters
        self._pipeline = pipeline
        self._sinks = list(sinks) if sinks else []
        self._event_bus = event_bus or EventBus()
        self.metrics = IngestionMetrics()
        self._tasks: list[asyncio.Task] = []

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    def add_sink(self, sink: FrameSink) -> None:
        self._sinks.append(sink)

    async def _handle_frame(self, raw_frame: RaceTelemetry, adapter: SourceAdapter) -> None:
        now = datetime.now(timezone.utc)

        try:
            validate_structure(raw_frame)
        except MalformedFrameError as exc:
            self.metrics.frames_malformed += 1
            log.warning(
                "malformed frame dropped",
                extra={"fields": {"reason": str(exc), "source": str(adapter.source_type)}},
            )
            return

        frame = raw_frame if raw_frame.ingest_timestamp is not None else raw_frame.model_copy(
            update={"ingest_timestamp": now}
        )

        result = self._pipeline.process(frame)
        self.metrics.frames_ingested += 1

        self._event_bus.publish(
            IngestionEvent(result=result, source=adapter.source_type, car_id=frame.car_id, received_at=now)
        )

        for sink in self._sinks:
            try:
                maybe_awaitable = sink(result)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
            except Exception as exc:  # noqa: BLE001 - sinks are untrusted downstream consumers
                self.metrics.sink_errors += 1
                log.error(
                    "sink raised while processing frame",
                    exc_info=True,
                    extra={"fields": {"sink": getattr(sink, "__name__", repr(sink)), "error": str(exc)}},
                )

    async def _run_adapter(self, adapter: SourceAdapter) -> None:
        name = f"{adapter.source_type.value}:{id(adapter)}"
        await adapter.connect()
        self.metrics.adapter_health[name] = adapter.health()
        try:
            async for raw_frame in adapter.stream():
                await self._handle_frame(raw_frame, adapter)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.metrics.adapter_errors += 1
            log.error(
                "adapter stream terminated by an error",
                exc_info=True,
                extra={"fields": {"source": str(adapter.source_type), "error": str(exc)}},
            )
        finally:
            await adapter.disconnect()

    async def run(self) -> None:
        """Run every adapter concurrently until each finishes (or is cancelled)."""

        self._tasks = [asyncio.create_task(self._run_adapter(a)) for a in self._adapters]
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
