"""DynamoDB metadata repository (single-table store)."""

from .metadata import (
    META_SK,
    DynamoMetadataRepository,
    MetadataRepository,
)

__all__ = ["META_SK", "DynamoMetadataRepository", "MetadataRepository"]
