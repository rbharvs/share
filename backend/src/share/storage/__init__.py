"""Object storage adapter (private/public S3 buckets)."""

from .object_storage import TMP_PREFIX, ObjectStorage, S3ObjectStorage

__all__ = ["TMP_PREFIX", "ObjectStorage", "S3ObjectStorage"]
