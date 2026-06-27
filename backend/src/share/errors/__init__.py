"""Domain errors and the structured error envelope."""

from .envelope import error_body, error_response
from .exceptions import (
    ERROR_CODES,
    AuthInvalidError,
    AuthRequiredError,
    ContentNotFoundError,
    HostNotAllowedError,
    InvalidUtf8Error,
    PublishFailedError,
    RouteNotAllowedError,
    ShareError,
    StorageError,
    UnpublishFailedError,
    UnsupportedSourceTypeError,
    UploadExpiredError,
    UploadNotFoundError,
    UploadNotUploadedError,
    UploadTooLargeError,
    ValidationError,
)

__all__ = [
    "ERROR_CODES",
    "AuthInvalidError",
    "AuthRequiredError",
    "ContentNotFoundError",
    "HostNotAllowedError",
    "InvalidUtf8Error",
    "PublishFailedError",
    "RouteNotAllowedError",
    "ShareError",
    "StorageError",
    "UnpublishFailedError",
    "UnsupportedSourceTypeError",
    "UploadExpiredError",
    "UploadNotFoundError",
    "UploadNotUploadedError",
    "UploadTooLargeError",
    "ValidationError",
    "error_body",
    "error_response",
]
