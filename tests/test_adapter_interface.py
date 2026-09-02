"""Tests for the SourceAdapter contract (backend/adapters/base.py).

No concrete adapter exists yet (Phase 2). These tests exercise the
interface itself with a minimal dummy implementation, so the contract is
validated before any real adapter is written against it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import pytest

from backend.adapters.base import AdapterHealth, SourceAdapter
from backend.telemetry.schema import DataSource, RaceTelemetry


def test_source_adapter_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        SourceAdapter()  # type: ignore[abstract]


class DummyAdapter(SourceAdapter):
    """Minimal in-memory adapter used only to validate the interface contract."""

    source_type = DataSource.SIMULATOR

    def __init__(self, frame_count: int = 3):
        self._frame_count = frame_count
        self._connected = False
        self._frames_received = 0

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def stream(self) -> AsyncIterator[RaceTelemetry]:
        for i in range(self._frame_count):
            self._frames_received += 1
            yield RaceTelemetry(
                source=self.source_type,
                source_timestamp=datetime(2026, 1, 1, 12, 0, i, tzinfo=timezone.utc),
                car_id="44",
                lap=1,
                sequence_id=i,
            )

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            connected=self._connected,
            source=self.source_type,
            frames_received=self._frames_received,
        )


@pytest.mark.asyncio
async def test_dummy_adapter_conforms_to_interface():
    adapter = DummyAdapter(frame_count=3)
    await adapter.connect()
    assert adapter.health().connected is True

    frames = [frame async for frame in adapter.stream()]

    assert len(frames) == 3
    assert all(isinstance(f, RaceTelemetry) for f in frames)
    assert [f.sequence_id for f in frames] == [0, 1, 2]
    assert adapter.health().frames_received == 3

    await adapter.disconnect()
    assert adapter.health().connected is False


@pytest.mark.asyncio
async def test_incomplete_adapter_cannot_be_instantiated():
    """An adapter missing any abstract method must fail to instantiate."""

    class IncompleteAdapter(SourceAdapter):
        source_type = DataSource.REAL_CAR

        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

        # `stream` and `health` deliberately not implemented.

    with pytest.raises(TypeError):
        IncompleteAdapter()  # type: ignore[abstract]
