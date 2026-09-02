"""Replays a previously stored sequence of `RaceTelemetry` frames.

Backs `evaluation/backtesting` (replay recorded/generated telemetry to
compare strategies) and `POST /api/replay/start`. Frames can come from an
in-memory sequence (e.g. output already captured from `SimulatorAdapter`,
used directly in a test) or a JSONL file (one JSON-encoded `RaceTelemetry`
per line) -- the on-disk format `simulator/replay` writes when persisting a
generated run.

Unlike `SimulatorAdapter`, replay has no content to (re)generate -- it
is reproducible by construction (the same file/sequence always yields the
same frames), so `seed` on its `ReplayDescriptor` is informational
(typically the seed the data was originally generated with), not something
this adapter itself consumes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator, Iterable, Optional, Sequence, Union

from backend.adapters.base import AdapterHealth, SourceAdapter
from backend.adapters.replay import ReplayDescriptor
from backend.observability.logging import get_logger
from backend.telemetry.schema import DataSource, RaceTelemetry

log = get_logger("adapters.replay")


def load_frames_jsonl(path: Union[str, Path]) -> list[RaceTelemetry]:
    frames: list[RaceTelemetry] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            frames.append(RaceTelemetry(**json.loads(line)))
    return frames


def save_frames_jsonl(frames: Iterable[RaceTelemetry], path: Union[str, Path]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for frame in frames:
            fh.write(frame.model_dump_json())
            fh.write("\n")


class ReplayAdapter(SourceAdapter):
    """Streams a fixed, pre-existing sequence of frames, in order."""

    source_type = DataSource.HISTORICAL_REPLAY

    def __init__(
        self,
        frames: Optional[Sequence[RaceTelemetry]] = None,
        file_path: Optional[Union[str, Path]] = None,
        scenario_id: str = "historical_replay",
        seed: int = 0,
        realtime: bool = False,
        speed_multiplier: float = 1.0,
    ):
        if (frames is None) == (file_path is None):
            raise ValueError("ReplayAdapter requires exactly one of `frames` or `file_path`")

        self._frames = list(frames) if frames is not None else None
        self._file_path = Path(file_path) if file_path is not None else None
        self._scenario_id = scenario_id
        self._seed = seed
        self._realtime = realtime
        self._speed_multiplier = max(speed_multiplier, 0.001)
        self._health = AdapterHealth(connected=False, source=self.source_type)

    async def connect(self) -> None:
        if self._frames is None:
            self._frames = load_frames_jsonl(self._file_path)  # type: ignore[arg-type]
        self._health.connected = True
        log.info(
            "replay adapter connected",
            extra={"fields": {"scenario_id": self._scenario_id, "frame_count": len(self._frames)}},
        )

    async def disconnect(self) -> None:
        self._health.connected = False

    def health(self) -> AdapterHealth:
        return self._health

    def replay_descriptor(self) -> ReplayDescriptor:
        return ReplayDescriptor(
            scenario_id=self._scenario_id,
            seed=self._seed,
            config={"frame_count": len(self._frames) if self._frames is not None else None},
        )

    async def stream(self) -> AsyncIterator[RaceTelemetry]:
        if not self._health.connected or self._frames is None:
            raise RuntimeError("ReplayAdapter.stream() called before connect()")

        last_ts = None
        for frame in self._frames:
            if self._realtime and last_ts is not None:
                delta_s = (frame.source_timestamp - last_ts).total_seconds()
                if delta_s > 0:
                    await asyncio.sleep(delta_s / self._speed_multiplier)
            last_ts = frame.source_timestamp

            self._health.frames_received += 1
            self._health.last_frame_timestamp = frame.source_timestamp.isoformat()
            yield frame
