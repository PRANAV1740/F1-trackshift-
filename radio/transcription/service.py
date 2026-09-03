"""Async radio transcription service.

Provides non-blocking speech-to-text / text ingestion for team radio messages.
Includes a deterministic text-based demo mode explicitly labeled as such (`is_demo_mode=True`).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.observability.logging import get_logger, log_and_continue
from radio.extraction.extractor import RadioIntentExtractor
from radio.model import DriverRadioMessage

log = get_logger("radio.transcription")


class RadioTranscriptionService:
    """Async, non-blocking radio message processing pipeline."""

    def __init__(self, extractor: Optional[RadioIntentExtractor] = None):
        self._extractor = extractor or RadioIntentExtractor()

    async def transcribe_and_extract_async(
        self,
        car_id: str,
        lap: int,
        raw_text: str,
        speaker: str = "DRIVER",
        timestamp: Optional[datetime] = None,
        is_demo_mode: bool = True,
    ) -> DriverRadioMessage:
        """Asynchronously processes a radio message transcript.

        Always yields control (`await asyncio.sleep(0)`) so it never blocks
        the main telemetry or strategy execution loop.
        """
        await asyncio.sleep(0)  # Guarantee non-blocking execution yield

        message_id = f"msg_{uuid.uuid4().hex[:8]}"

        try:
            message = self._extractor.process_transcript(
                message_id=message_id,
                car_id=car_id,
                lap=lap,
                raw_text=raw_text,
                speaker=speaker,
                timestamp=timestamp or datetime.now(timezone.utc),
                is_demo_mode=is_demo_mode,
            )
            log.info(
                "radio message processed",
                extra={
                    "fields": {
                        "message_id": message.message_id,
                        "car_id": car_id,
                        "lap": lap,
                        "intents": [i.value for i in message.detected_intents],
                        "is_demo_mode": is_demo_mode,
                    }
                },
            )
            return message
        except Exception as e:
            log.error("error processing radio transcript", extra={"fields": {"error": str(e)}})
            # Return safe fallback
            return DriverRadioMessage(
                message_id=message_id,
                car_id=car_id,
                lap=lap,
                timestamp=timestamp or datetime.now(timezone.utc),
                speaker=speaker,
                raw_text=raw_text,
                detected_intents=[],
                confidence=0.0,
                is_demo_mode=is_demo_mode,
            )
