from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.telemetry.schema import DataSource, RaceTelemetry


@pytest.fixture
def base_frame_kwargs() -> dict:
    """The minimal set of fields required to construct a RaceTelemetry frame."""

    return dict(
        source=DataSource.SIMULATOR,
        source_timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        car_id="44",
        lap=1,
    )


@pytest.fixture
def sample_frame(base_frame_kwargs: dict) -> RaceTelemetry:
    return RaceTelemetry(
        **base_frame_kwargs,
        position=3,
        speed_kph=287.4,
        tyre_age_laps=5,
        fuel_load_kg=62.1,
    )
