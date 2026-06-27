"""Tests for the error envelope primitive and the full error-code surface."""

from __future__ import annotations

import json

from share.errors import ERROR_CODES, ShareError, UploadTooLargeError, error_response

EXPECTED_CODES = {
    "auth_required",
    "auth_invalid",
    "host_not_allowed",
    "route_not_allowed",
    "validation_error",
    "upload_not_found",
    "upload_expired",
    "upload_not_uploaded",
    "upload_too_large",
    "unsupported_source_type",
    "invalid_utf8",
    "content_not_found",
    "publish_failed",
    "unpublish_failed",
    "storage_error",
}


def test_all_prd_error_codes_exist_as_subclasses():
    assert set(ERROR_CODES) == EXPECTED_CODES
    for code, cls in ERROR_CODES.items():
        assert issubclass(cls, ShareError)
        assert cls.code == code
        assert isinstance(cls.status_code, int)


def test_error_response_envelope_shape():
    resp = error_response(UploadTooLargeError(), "req-123")
    assert resp.status_code == 413
    body = json.loads(resp.body)
    assert body == {
        "error": {
            "code": "upload_too_large",
            "message": "Uploads are limited to 5 MB.",
            "request_id": "req-123",
        }
    }


def test_error_response_custom_message():
    resp = error_response(UploadTooLargeError("too big"), None)
    body = json.loads(resp.body)
    assert body["error"]["message"] == "too big"
    assert body["error"]["request_id"] is None
