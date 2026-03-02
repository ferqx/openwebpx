from __future__ import annotations

import logging

from app.logging_filters import (
    SuppressFinishedBrokerLateEventFilter,
    install_broker_late_event_filter,
)


def _record(msg: object) -> logging.LogRecord:
    return logging.LogRecord(
        name="aegra_api.services.broker",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_filter_blocks_finished_broker_late_event_string_message() -> None:
    filt = SuppressFinishedBrokerLateEventFilter()

    record = _record("Attempted to put event e-1 into finished broker for run r-1")

    assert filt.filter(record) is False


def test_filter_blocks_finished_broker_late_event_structlog_dict() -> None:
    filt = SuppressFinishedBrokerLateEventFilter()

    record = _record(
        {
            "event": "Attempted to put event e-1 into finished broker for run r-1",
            "level": "warning",
        }
    )

    assert filt.filter(record) is False


def test_filter_allows_other_broker_warnings() -> None:
    filt = SuppressFinishedBrokerLateEventFilter()

    record = _record("broker cleanup task failed")

    assert filt.filter(record) is True


def test_install_filter_is_idempotent() -> None:
    logger = logging.getLogger("aegra_api.services.broker")
    logger.filters = [
        existing
        for existing in logger.filters
        if not isinstance(existing, SuppressFinishedBrokerLateEventFilter)
    ]

    install_broker_late_event_filter()
    install_broker_late_event_filter()

    matching = [
        existing
        for existing in logger.filters
        if isinstance(existing, SuppressFinishedBrokerLateEventFilter)
    ]
    assert len(matching) == 1
