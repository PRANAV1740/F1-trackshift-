"""Tests for Phase 29 Demo Mode (`demo.py`)."""

from __future__ import annotations

import pytest
from demo import run_terminal_demo


def test_demo_mode_executes_preset_scenarios():
    for scenario_id in ["normal_race", "tyre_cliff", "rain_arrival", "driver_disagreement"]:
        # High speed multiplier (100.0x) for fast test execution
        run_terminal_demo(scenario_id=scenario_id, speed=100.0)
