"""The opaque pagination cursor: a base64url-wrapped DynamoDB pagination token.

The cursor is *opaque* by contract — clients must treat it as a blob and only
echo it back. Internally it is the base64url-encoded JSON of DynamoDB's
``LastEvaluatedKey`` (``{"pk": ..., "sk": ...}``), so a resumed listing seeks
straight to the next item with no scan and no re-read of earlier pages.

Cursors arrive from the network, so :func:`decode_cursor` treats any malformed
input as a client error (:class:`~share.errors.ValidationError`) rather than a
500 — a tampered or stale cursor must never crash the listing endpoint.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from share.errors import ValidationError


def encode_cursor(last_evaluated_key: dict[str, Any]) -> str:
    """Encode a DynamoDB ``LastEvaluatedKey`` into an opaque base64url cursor."""

    raw = json.dumps(last_evaluated_key, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode an opaque cursor back into a DynamoDB ``ExclusiveStartKey``.

    Raises :class:`~share.errors.ValidationError` if the cursor is not valid
    base64url, not valid UTF-8 JSON, or does not decode to a JSON object.
    """

    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        decoded = json.loads(raw.decode("utf-8"))
    except (
        binascii.Error,
        ValueError,
        UnicodeDecodeError,
    ) as exc:
        raise ValidationError("The pagination cursor is invalid.") from exc

    if not isinstance(decoded, dict):
        raise ValidationError("The pagination cursor is invalid.")

    return decoded
