"""Deterministic-replay contract.

Protocol requirement: the same `(scenario_id, seed, configuration)` must
always produce the same output. This module defines the descriptor that
makes that contract explicit and checkable, and a small protocol that any
reproducible adapter (simulator, replay reader) implements.

Nothing here performs randomness itself -- `backend/observability` has no
opinion on how a seed is consumed. This just gives every reproducible
source one common, hashable way to declare "here is exactly what
configuration produced this run", so two runs can be compared for equality
and a scenario can be re-run byte-for-byte later (evaluation/backtesting,
the scenario suite, and the demo all depend on this).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


def _stable_hash(config: dict[str, Any]) -> str:
    canonical = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ReplayDescriptor:
    """Everything needed to reproduce a run byte-for-byte."""

    scenario_id: str
    seed: int
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def config_hash(self) -> str:
        return _stable_hash(self.config)

    @property
    def run_id(self) -> str:
        """A stable identifier for this exact (scenario, seed, config) triple."""

        return f"{self.scenario_id}:{self.seed}:{self.config_hash}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "config": self.config,
            "config_hash": self.config_hash,
            "run_id": self.run_id,
        }


@runtime_checkable
class ReplayCapable(Protocol):
    """Implemented by any adapter whose output must be reproducible.

    A `SourceAdapter` (backend/adapters/base.py) that also implements this
    protocol -- the simulator and historical-replay adapters, not a real
    telemetry link -- declares its descriptor up front so callers (the
    scenario suite, evaluation/backtesting, demo mode) can log exactly what
    produced a given run and re-run it later.
    """

    def replay_descriptor(self) -> ReplayDescriptor: ...
