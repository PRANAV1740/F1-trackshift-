"""Radio intent extraction engine.

Parses transcribed text to detect driver-reported states and strategic requests
(tyre issues, traffic, rain, pit requests).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from radio.model import DriverRadioMessage, RadioIntent

# Deterministic keyword patterns for intent extraction
INTENT_PATTERNS: list[tuple[RadioIntent, re.Pattern]] = [
    (RadioIntent.TYRE_GRAINING, re.compile(r"\b(graining|grain|deg|degrading|going off|losing grip)\b", re.IGNORECASE)),
    (RadioIntent.TYRE_OVERHEATING, re.compile(r"\b(overheating|overheat|temps high|temperature|hot)\b", re.IGNORECASE)),
    (RadioIntent.TYRE_PUNCTURE, re.compile(r"\b(puncture|flat|deflating|loss of pressure|vibration)\b", re.IGNORECASE)),
    (RadioIntent.TRAFFIC_HEAVY, re.compile(r"\b(traffic|stuck behind|held up|can't pass|dirty air)\b", re.IGNORECASE)),
    (RadioIntent.RAIN_REPORTED, re.compile(r"\b(rain|drops|wet|damp|spotting|slippery|water)\b", re.IGNORECASE)),
    (RadioIntent.BRAKE_BAL_ISSUE, re.compile(r"\b(brake|braking|long pedal|lockup|locking)\b", re.IGNORECASE)),
    (RadioIntent.STRATEGY_PIT_REQUEST, re.compile(r"\b(box|pit|change tyres|new tyres|in this lap|come in)\b", re.IGNORECASE)),
    (RadioIntent.STRATEGY_STAY_OUT_REQUEST, re.compile(r"\b(stay out|keep going|tyres feel fine|tyres are good|no pit)\b", re.IGNORECASE)),
]


class RadioIntentExtractor:
    """Extracts semantic intents from driver or engineer radio transcripts."""

    def extract_intents(self, text: str) -> list[RadioIntent]:
        intents: list[RadioIntent] = []
        for intent, pattern in INTENT_PATTERNS:
            if pattern.search(text):
                intents.append(intent)
        if not intents:
            intents.append(RadioIntent.UNKNOWN)
        return intents

    def process_transcript(
        self,
        message_id: str,
        car_id: str,
        lap: int,
        raw_text: str,
        speaker: str = "DRIVER",
        timestamp: Optional[datetime] = None,
        is_demo_mode: bool = True,
    ) -> DriverRadioMessage:
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        intents = self.extract_intents(raw_text)
        confidence = 0.95 if intents != [RadioIntent.UNKNOWN] else 0.5

        return DriverRadioMessage(
            message_id=message_id,
            car_id=car_id,
            lap=lap,
            timestamp=timestamp,
            speaker=speaker.upper(),
            raw_text=raw_text,
            detected_intents=intents,
            confidence=confidence,
            is_demo_mode=is_demo_mode,
        )
