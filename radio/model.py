"""Radio intelligence data structures and intent vocabulary.

Defines driver/engineer radio messages and intent classifications (tyre issues,
weather/traffic reports, strategy requests).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class RadioIntent(str, Enum):
    TYRE_GRAINING = "TYRE_GRAINING"
    TYRE_OVERHEATING = "TYRE_OVERHEATING"
    TYRE_PUNCTURE = "TYRE_PUNCTURE"
    TRAFFIC_HEAVY = "TRAFFIC_HEAVY"
    RAIN_REPORTED = "RAIN_REPORTED"
    BRAKE_BAL_ISSUE = "BRAKE_BAL_ISSUE"
    STRATEGY_PIT_REQUEST = "STRATEGY_PIT_REQUEST"
    STRATEGY_STAY_OUT_REQUEST = "STRATEGY_STAY_OUT_REQUEST"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DriverRadioMessage:
    message_id: str
    car_id: str
    lap: int
    timestamp: datetime
    speaker: str  # "DRIVER" or "ENGINEER"
    raw_text: str
    detected_intents: list[RadioIntent] = field(default_factory=list)
    confidence: float = 1.0
    is_demo_mode: bool = True  # Explicitly labeled deterministic text demo mode
