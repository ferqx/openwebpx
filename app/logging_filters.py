from __future__ import annotations

import logging
from typing import Any

_BROKER_LATE_EVENT_PREFIX = "Attempted to put event"
_BROKER_LATE_EVENT_SUFFIX = "into finished broker for run"


class SuppressFinishedBrokerLateEventFilter(logging.Filter):
    """Suppress benign late-event warnings emitted after run broker is finished."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = _extract_log_message(record)
        return not (
            _BROKER_LATE_EVENT_PREFIX in message
            and _BROKER_LATE_EVENT_SUFFIX in message
        )


def install_broker_late_event_filter(
    *,
    logger_name: str = "aegra_api.services.broker",
) -> None:
    """Install idempotent filter to silence known benign broker warning."""
    logger = logging.getLogger(logger_name)
    if any(
        isinstance(existing, SuppressFinishedBrokerLateEventFilter)
        for existing in logger.filters
    ):
        return
    logger.addFilter(SuppressFinishedBrokerLateEventFilter())


def _extract_log_message(record: logging.LogRecord) -> str:
    """Extract normalized message from plain or structlog-style records."""
    msg: Any = record.msg
    if isinstance(msg, dict):
        event_value = msg.get("event")
        if isinstance(event_value, str):
            return event_value
        return str(msg)
    try:
        return record.getMessage()
    except Exception:  # pragma: no cover - defensive fallback
        return str(msg)
