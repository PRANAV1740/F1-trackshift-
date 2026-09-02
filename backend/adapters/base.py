"""Source adapter interfaces.

A source adapter is the only layer permitted to know about a specific
telemetry origin: a real car's telemetry link, the in-repo simulator, or a
historical/replay data store. Its sole job is translating whatever raw
shape its source produces into the common `RaceTelemetry` schema
(backend/telemetry/schema.py). Adapters must NOT normalize, smooth,
interpolate, or otherwise clean the data -- that is the normalization
pipeline's job (backend/normalization/base.py), and keeping the boundary
strict is what lets the same downstream pipeline run unmodified against
any source.

Concrete adapters (real telemetry link, simulator feed, replay reader) are
implemented in later phases. This module defines the contract they satisfy.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from backend.telemetry.schema import DataSource, RaceTelemetry


@dataclass
class AdapterHealth:
    """Connection/throughput health, for observability (see docs/ARCHITECTURE.md)."""

    connected: bool
    source: DataSource
    frames_received: int = 0
    frames_dropped: int = 0
    last_frame_timestamp: Optional[str] = None
    last_error: Optional[str] = None


class SourceAdapter(abc.ABC):
    """Common contract for all telemetry source adapters.

    An implementation wraps exactly one origin and must not perform
    normalization or business logic -- only translation into
    `RaceTelemetry`. Frames yielded by `stream()` may be imperfect (missing
    fields, duplicates, out-of-order timestamps, sensor spikes): adapters
    must pass such frames through as-is rather than silently repairing or
    dropping them, so that behavior is visible to and testable by the
    normalization pipeline.
    """

    source_type: DataSource

    @abc.abstractmethod
    async def connect(self) -> None:
        """Establish the underlying connection/session. Must be idempotent."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Tear down the underlying connection/session. Must be idempotent."""

    @abc.abstractmethod
    def stream(self) -> AsyncIterator[RaceTelemetry]:
        """Yield raw, not-yet-normalized `RaceTelemetry` frames as they arrive."""

    @abc.abstractmethod
    def health(self) -> AdapterHealth:
        """Return current connection/throughput health."""
