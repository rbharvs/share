"""CDN invalidation seam for the publish vertical.

Unpublish (and any future republish) must purge the CloudFront edge caches for
the public artifact. The real boto3 CloudFront client needs the distribution id,
which does not exist until the CDN is provisioned (slice 13), so the dependency
is hidden behind a tiny :class:`Invalidator` Protocol. This slice ships a no-op
default (:class:`NullInvalidator`) for the running app and a
:class:`RecordingInvalidator` fake so publish/unpublish — including the exact
rewritten cache-key path — are fully testable before any cloud exists.

The invalidated path is the rewritten CloudFront cache key
(``/u/{sha}/index.html``), computed by
:func:`share.publish.service.invalidation_paths` from the public object key — see
that function for why the bare ``/u/{sha}`` shapes would miss the real edge cache.

The real :class:`CloudFrontInvalidator` (slice 13) implements the same one-method
interface against boto3; nothing in the service changes when it is swapped in.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from botocore.exceptions import ClientError

from share.errors import UnpublishFailedError


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

    Lets the publish/unpublish tests assert the computed rewritten cache-key path
    without a real CloudFront distribution.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def invalidate(self, paths: list[str]) -> None:  # noqa: D102
        self.calls.append(list(paths))


class CloudFrontInvalidator:
    """Real :class:`Invalidator` backed by a boto3 CloudFront client (slice 13).

    Submits one ``CreateInvalidation`` per batch against the public
    distribution. The caller-supplied ``paths`` are already the rewritten
    cache-key path computed by :func:`share.publish.service.invalidation_paths`,
    so this adapter only has to wrap them in an invalidation batch with a unique
    ``CallerReference`` (CloudFront rejects duplicate references / re-uses the
    prior batch, so each request gets a fresh one).

    A CloudFront failure surfaces as :class:`UnpublishFailedError` rather than a
    raw boto3 ``ClientError`` so the central error mapper can render it, and so a
    failed purge does NOT silently mark the item unpublished while stale bytes
    still live at the edge — the operation can be safely retried (object delete
    and re-invalidation are both idempotent).
    """

    def __init__(
        self,
        *,
        client: Any,
        distribution_id: str,
        reference_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self._client = client
        self._distribution_id = distribution_id
        self._reference_factory = reference_factory

    def invalidate(self, paths: list[str]) -> None:  # noqa: D102
        if not paths:
            return
        try:
            self._client.create_invalidation(
                DistributionId=self._distribution_id,
                InvalidationBatch={
                    "Paths": {"Quantity": len(paths), "Items": list(paths)},
                    "CallerReference": self._reference_factory(),
                },
            )
        except ClientError as exc:
            raise UnpublishFailedError(
                "Invalidating the CloudFront cache failed."
            ) from exc
