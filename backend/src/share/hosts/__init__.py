"""Shared host registry."""

from .registry import (
    DEFAULT_HOST_KINDS,
    LOCAL_HOST_KINDS,
    PROD_HOST_KINDS,
    HostKind,
    classify_host,
)

__all__ = [
    "DEFAULT_HOST_KINDS",
    "LOCAL_HOST_KINDS",
    "PROD_HOST_KINDS",
    "HostKind",
    "classify_host",
]
