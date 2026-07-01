"""JSON structured logging for ReliQueue workers."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger("reliqueue.worker")


def _serialize(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def format_event(event: str, **fields: Any) -> str:
    """Build a single-line JSON string for a worker lifecycle event."""
    payload: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
    }
    for key, value in fields.items():
        if value is not None:
            payload[key] = _serialize(value)

    return json.dumps(payload, separators=(",", ":"))


def emit(event: str, **fields: Any) -> None:
    """Emit a single-line JSON log record for worker lifecycle events."""
    logger.info(format_event(event, **fields))


def configure_worker_logging() -> None:
    """Configure root logging so worker JSON records are emitted one per line."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        force=True,
    )
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
