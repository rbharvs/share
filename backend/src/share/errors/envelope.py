"""The single error-response primitive.

``error_response`` is shared by BOTH the FastAPI exception handlers AND the gate
middleware (which sits outside the FastAPI handler stack and must map inline).
There is exactly one place that knows the envelope shape.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from .exceptions import ShareError


def error_body(exc: ShareError, request_id: str | None) -> dict[str, Any]:
    """Build the structured error envelope dict."""

    return {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "request_id": request_id,
        }
    }


def error_response(exc: ShareError, request_id: str | None) -> JSONResponse:
    """Convert a :class:`ShareError` into the structured JSON error response.

    Envelope shape::

        {"error": {"code", "message", "request_id"}}
    """

    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc, request_id),
    )
