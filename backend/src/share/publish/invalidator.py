"""CDN invalidation seam for the publish vertical.

Unpublish (and any future republish) must purge the CloudFront edge caches for
the public artifact. The real boto3 CloudFront client needs the distribution id,
which does not exist until the CDN is provisioned (slice 13), so the dependency
is hidden behind a tiny :class:`Invalidator` Protocol. This slice ships a no-op
default (:class:`NullInvalidator`) for the running app and a
:class:`RecordingInvalidator` fake so publish/unpublish — including the exact
slash + no-slash invalidation paths — are fully testable before any cloud exists.

The real ``CloudFrontInvalidator`` is dropped in at slice 13 by implementing the
same one-method interface; nothing in the service changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Invalidator(Protocol):
    """Purge a batch of CDN paths so the edge re-fetches from the origin."""

    def invalidate(self, paths: list[str]) -> None:
        """Invalidate ``paths`` (CDN-rooted, e.g. ``/u/{sha}``)."""


class NullInvalidator:
    """No-op default until the CloudFront client arrives (slice 13).

    Publish/unpublish stay correct without a CDN: the public bucket is written
    and deleted regardless; only the edge-cache purge is deferred.
    """

    def invalidate(self, paths: list[str]) -> None:  # noqa: D102
        return None


class RecordingInvalidator:
    """Test fake recording every batch of paths it was asked to invalidate.

    Lets the publish/unpublish tests assert the computed slash + no-slash paths
    without a real CloudFront distribution.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def invalidate(self, paths: list[str]) -> None:  # noqa: D102
        self.calls.append(list(paths))
