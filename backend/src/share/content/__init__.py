"""Content domain primitives shared across renderer, upload, and storage."""

from .limits import MAX_UPLOAD_BYTES
from .source_type import SourceType

__all__ = ["MAX_UPLOAD_BYTES", "SourceType"]
