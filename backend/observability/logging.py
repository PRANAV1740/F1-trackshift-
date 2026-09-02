"""Structured logging used across every backend module.

Rule 18 of the project's engineering rules is "never silently swallow
errors." This module makes that easy to honor: `get_logger(name)` returns a
stdlib `Logger` that emits single-line JSON records (easy to grep, easy to
feed into `evaluation/` later), and `log_and_continue` is the one approved
way to catch-and-degrade in an optional subsystem (Phase 26 failure
handling) -- it always logs at ERROR with the exception, never just
`except Exception: pass`.

This is deliberately not a metrics/tracing system -- just consistent,
structured logs. A real deployment would swap the handler for something
that ships logs elsewhere; nothing downstream should depend on that.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure_once() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("race_intelligence")
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under the `race_intelligence` root.

    Usage: `log = get_logger(__name__)` then `log.info("msg", extra={"fields": {...}})`.
    """

    _configure_once()
    return logging.getLogger(f"race_intelligence.{name}")


@contextmanager
def log_and_continue(logger: logging.Logger, operation: str, **fields: Any) -> Iterator[None]:
    """Run a block; on exception, log it with full context and re-raise nothing.

    Intended only for genuinely optional subsystems (Phase 26): a failed
    radio-extraction call or a missing weather feed must not take down the
    telemetry decision path. It is NOT for the core pipeline (ingestion,
    normalization, state, strategy) -- those should fail loudly.
    """

    start = time.perf_counter()
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - this is the one sanctioned catch-all
        logger.error(
            "%s failed: %s",
            operation,
            exc,
            exc_info=True,
            extra={"fields": {"operation": operation, "degraded": True, **fields}},
        )
    else:
        logger.debug(
            "%s ok",
            operation,
            extra={
                "fields": {
                    "operation": operation,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 3),
                    **fields,
                }
            },
        )
