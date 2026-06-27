"""Domain exceptions for the share service.

Every PRD error code exists up front as a :class:`ShareError` subclass carrying
a stable ``code`` and an HTTP ``status_code``. Service code raises these; the
API boundary (and the gate middleware) convert them to the structured error
envelope via :func:`share.errors.envelope.error_response`.
"""

from __future__ import annotations


class ShareError(Exception):
    """Base class for all domain errors.

    Subclasses set :attr:`code` (the stable, client-facing error code) and
    :attr:`status_code` (the HTTP status). ``message`` is human-readable and
    safe to surface to the dashboard UI.
    """

    code: str = "storage_error"
    status_code: int = 500
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        self.message = message if message is not None else self.default_message
        super().__init__(self.message)


class AuthRequiredError(ShareError):
    code = "auth_required"
    status_code = 401
    default_message = "Authentication is required."


class AuthInvalidError(ShareError):
    code = "auth_invalid"
    status_code = 401
    default_message = "Authentication credentials are invalid."


class HostNotAllowedError(ShareError):
    code = "host_not_allowed"
    status_code = 403
    default_message = "This host is not allowed."


class RouteNotAllowedError(ShareError):
    code = "route_not_allowed"
    status_code = 403
    default_message = "This route is not allowed for this host."


class ValidationError(ShareError):
    code = "validation_error"
    status_code = 422
    default_message = "The request was invalid."


class UploadNotFoundError(ShareError):
    code = "upload_not_found"
    status_code = 404
    default_message = "The upload session was not found."


class UploadExpiredError(ShareError):
    code = "upload_expired"
    status_code = 410
    default_message = "The upload session has expired."


class UploadNotUploadedError(ShareError):
    code = "upload_not_uploaded"
    status_code = 409
    default_message = "The upload was not completed."


class UploadTooLargeError(ShareError):
    code = "upload_too_large"
    status_code = 413
    default_message = "Uploads are limited to 5 MB."


class UnsupportedSourceTypeError(ShareError):
    code = "unsupported_source_type"
    status_code = 415
    default_message = "The source type is not supported."


class InvalidUtf8Error(ShareError):
    code = "invalid_utf8"
    status_code = 400
    default_message = "The uploaded bytes are not valid UTF-8."


class ContentNotFoundError(ShareError):
    code = "content_not_found"
    status_code = 404
    default_message = "The content item was not found."


class PublishFailedError(ShareError):
    code = "publish_failed"
    status_code = 500
    default_message = "Publishing the content item failed."


class UnpublishFailedError(ShareError):
    code = "unpublish_failed"
    status_code = 500
    default_message = "Unpublishing the content item failed."


class StorageError(ShareError):
    code = "storage_error"
    status_code = 500
    default_message = "A storage operation failed."


#: Every concrete error code shipped in v1, keyed by stable code string.
ERROR_CODES: dict[str, type[ShareError]] = {
    cls.code: cls
    for cls in (
        AuthRequiredError,
        AuthInvalidError,
        HostNotAllowedError,
        RouteNotAllowedError,
        ValidationError,
        UploadNotFoundError,
        UploadExpiredError,
        UploadNotUploadedError,
        UploadTooLargeError,
        UnsupportedSourceTypeError,
        InvalidUtf8Error,
        ContentNotFoundError,
        PublishFailedError,
        UnpublishFailedError,
        StorageError,
    )
}
