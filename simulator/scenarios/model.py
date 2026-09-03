"""Scenario model definitions.

Represents a named, seeded scenario with deterministic configurations for
telemetry generation, event injection, weather transitions, pit stops, and
radio messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from radio.model import DriverRadioMessage
from simulator.generator.core import GeneratorConfig
from simulator.generator.noise import NoiseConfig


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    name: str
    description: str
    seed: int
    generator_configs: dict[str, GeneratorConfig] = field(default_factory=dict)
    radio_messages: list[DriverRadioMessage] = field(default_factory=list)

    @property
    def primary_car_id(self) -> str:
        return next(iter(self.generator_configs.keys()), "44")
