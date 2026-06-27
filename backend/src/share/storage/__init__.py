"""Object storage adapter (private/public S3 buckets)."""

from .object_storage import (
    ARTIFACTS_PREFIX,
    PUBLIC_PREFIX,
    RAW_PREFIX,
    TMP_PREFIX,
    ObjectStorage,
    S3ObjectStorage,
)

__all__ = [
    "ARTIFACTS_PREFIX",
    "PUBLIC_PREFIX",
    "RAW_PREFIX",
    "TMP_PREFIX",
    "ObjectStorage",
    "S3ObjectStorage",
]
