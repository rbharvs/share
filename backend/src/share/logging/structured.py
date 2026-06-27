"""Structured JSON request logging.

One JSON line per request, emitted on the ``share.request`` logger. The line
carries the request context (``request_id``, host, path, method, status). Later
slices extend the context with user email / action / short SHA without changing
the emit shape.
"""

from __future__ import annotations

import json
import logging
from typing import Any

REQUEST_LOGGER_NAME = "share.request"

_logger = logging.getLogger(REQUEST_LOGGER_NAME)


def log_request(
    *,
    request_id: str,
    host: str | None,
    path: str,
    method: str,
    status: int,
    **extra: Any,
) -> None:
    """Emit exactly one structured JSON log line for a handled request."""

    payload: dict[str, Any] = {
        "request_id": request_id,
        "host": host,
        "path": path,
        "method": method,
        "status": status,
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    _logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))
