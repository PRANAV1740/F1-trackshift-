"""Tests for Phase 16 -- Radio Intelligence (`radio/`)."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from radio.extraction.extractor import RadioIntentExtractor
from radio.model import DriverRadioMessage, RadioIntent
from radio.transcription.service import RadioTranscriptionService

BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_intent_extractor_identifies_tyre_graining():
    extractor = RadioIntentExtractor()
    text = "The front left is graining badly, losing grip"
    intents = extractor.extract_intents(text)
    assert RadioIntent.TYRE_GRAINING in intents


def test_intent_extractor_identifies_pit_request():
    extractor = RadioIntentExtractor()
    text = "Box this lap, tyres are completely done"
    intents = extractor.extract_intents(text)
    assert RadioIntent.STRATEGY_PIT_REQUEST in intents


def test_intent_extractor_identifies_multiple_intents():
    extractor = RadioIntentExtractor()
    text = "Stuck behind traffic and rear temps high"
    intents = extractor.extract_intents(text)
    assert RadioIntent.TRAFFIC_HEAVY in intents
    assert RadioIntent.TYRE_OVERHEATING in intents


def test_intent_extractor_unknown_fallback():
    extractor = RadioIntentExtractor()
    text = "Radio check 1 2 3"
    intents = extractor.extract_intents(text)
    assert intents == [RadioIntent.UNKNOWN]


def test_process_transcript_creates_demo_mode_message():
    extractor = RadioIntentExtractor()
    msg = extractor.process_transcript(
        message_id="msg1",
        car_id="44",
        lap=12,
        raw_text="Seeing rain in sector 2",
        timestamp=BASE_TS,
    )
    assert isinstance(msg, DriverRadioMessage)
    assert msg.car_id == "44"
    assert msg.lap == 12
    assert RadioIntent.RAIN_REPORTED in msg.detected_intents
    assert msg.is_demo_mode is True


@pytest.mark.asyncio
async def test_transcription_service_async_processing():
    service = RadioTranscriptionService()
    msg = await service.transcribe_and_extract_async(
        car_id="44",
        lap=15,
        raw_text="Tyres feel fine, stay out",
        speaker="DRIVER",
        timestamp=BASE_TS,
    )

    assert msg.car_id == "44"
    assert msg.lap == 15
    assert msg.speaker == "DRIVER"
    assert RadioIntent.STRATEGY_STAY_OUT_REQUEST in msg.detected_intents
    assert msg.is_demo_mode is True
