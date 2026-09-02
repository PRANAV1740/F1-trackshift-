"""Tests for backend/observability/logging.py."""

from __future__ import annotations

import logging

from backend.observability.logging import get_logger, log_and_continue


def test_get_logger_is_namespaced_under_race_intelligence():
    log = get_logger("tyre.model")
    assert log.name == "race_intelligence.tyre.model"


def test_log_and_continue_swallows_exception_and_logs_error(caplog):
    log = get_logger("test.degraded")

    with caplog.at_level(logging.ERROR, logger=log.name):
        with log_and_continue(log, "fetch_weather", car_id="44"):
            raise RuntimeError("weather feed unavailable")

    assert any("fetch_weather failed" in record.message for record in caplog.records)
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_log_and_continue_does_not_swallow_returned_value_flow():
    """Confirms code after the block still runs normally when no exception occurs."""

    log = get_logger("test.ok")
    ran_after = False

    with log_and_continue(log, "noop"):
        pass
    ran_after = True

    assert ran_after is True
