"""Placeholder for a real telemetry-link adapter.

No such link is implemented, configured, or available in this project.
This class exists only to make the future integration point concrete: it
satisfies the `SourceAdapter` contract structurally (so it type-checks and
can be swapped in wherever an adapter is expected), but every method that
would need an actual connection raises `NotImplementedError` with a clear
message rather than pretending to succeed. See engineering rule 8: do not
claim real F1 integration unless it is actually implemented.

A real implementation would, at minimum, need: a connection endpoint and
protocol for whatever telemetry link is being integrated (team-internal
UDP/TCP stream, vendor API, etc.), authentication/credentials, and a
parser translating that wire format into `RaceTelemetry` -- structurally
no different from `SimulatorAdapter`, just with a real source instead of
a generator.
"""

from __future__ import annotations

from typing import AsyncIterator, Optional

from backend.adapters.base import AdapterHealth, SourceAdapter
from backend.telemetry.schema import DataSource, RaceTelemetry

_NOT_IMPLEMENTED_MESSAGE = (
    "RealCarAdapter has no telemetry link configured. This project does not "
    "claim any real F1/telemetry integration -- use SimulatorAdapter or "
    "ReplayAdapter for development, testing, and demos."
)


class RealCarAdapter(SourceAdapter):
    source_type = DataSource.REAL_CAR

    def __init__(self, connection_endpoint: Optional[str] = None):
        self._connection_endpoint = connection_endpoint
        self._health = AdapterHealth(connected=False, source=self.source_type, last_error=_NOT_IMPLEMENTED_MESSAGE)

    async def connect(self) -> None:
        self._health.last_error = _NOT_IMPLEMENTED_MESSAGE
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    async def disconnect(self) -> None:
        self._health.connected = False

    def health(self) -> AdapterHealth:
        return self._health

    async def stream(self) -> AsyncIterator[RaceTelemetry]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)
        yield  # pragma: no cover - makes this an async generator function
