"""A minimal async pub/sub bus for ingested-frame events.

Exists so downstream consumers (the WebSocket layer in a later phase, the
event detection engine, a demo-mode UI feed) can subscribe to normalized
frames without ingestion knowing anything about them. Bounded per-subscriber
queues with drop-oldest overflow keep one slow subscriber from ever
blocking ingestion itself -- backpressure is absorbed by dropping the
subscriber's oldest buffered event (logged), never by stalling the pipeline.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from backend.normalization.base import NormalizationResult
from backend.observability.logging import get_logger
from backend.telemetry.schema import DataSource

log = get_logger("ingestion.bus")


@dataclass
class IngestionEvent:
    result: NormalizationResult
    source: DataSource
    car_id: str
    received_at: datetime


class EventBus:
    def __init__(self, max_queue_size: int = 1000):
        self._subscribers: list[asyncio.Queue] = []
        self._max_queue_size = max_queue_size

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def publish(self, event: IngestionEvent) -> None:
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                    log.warning(
                        "subscriber queue full, dropped oldest event",
                        extra={"fields": {"car_id": event.car_id}},
                    )
                except asyncio.QueueEmpty:
                    pass
