"""Unit tests for the real CloudFront invalidator and its DI wiring (slice 13).

The publish/unpublish HTTP tests already prove the *service* hands the rewritten
cache-key path to the :class:`Invalidator` seam (via the recording fake). These
tests prove the real :class:`CloudFrontInvalidator` faithfully forwards that path
to ``CreateInvalidation`` and that ``get_invalidator`` only selects it once a
distribution id is configured.
"""

from __future__ import annotations

from itertools import count
from typing import Any

import pytest
from botocore.exceptions import ClientError

from share.config import Settings
from share.errors import UnpublishFailedError
from share.publish import (
    CloudFrontInvalidator,
    NullInvalidator,
    invalidation_paths,
)
from share.publish.dependencies import _cloudfront_invalidator, get_invalidator

DISTRIBUTION_ID = "E1234567890ABC"


class FakeCloudFrontClient:
    """Records every ``create_invalidation`` call instead of hitting AWS."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_invalidation(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"Invalidation": {"Id": f"I{len(self.calls)}"}}


class BrokenCloudFrontClient:
    """Raises a boto3 ``ClientError`` like a throttled/denied CloudFront API."""

    def create_invalidation(self, **kwargs: Any) -> dict[str, Any]:
        raise ClientError(
            {"Error": {"Code": "Throttling", "Message": "Rate exceeded"}},
            "CreateInvalidation",
        )


def _make(client: Any) -> CloudFrontInvalidator:
    # Deterministic caller references so assertions stay stable.
    refs = count()
    return CloudFrontInvalidator(
        client=client,
        distribution_id=DISTRIBUTION_ID,
        reference_factory=lambda: f"ref-{next(refs)}",
    )


def test_forwards_rewritten_cache_key_path_as_one_batch() -> None:
    client = FakeCloudFrontClient()
    paths = invalidation_paths("u/abc123/index.html")

    _make(client).invalidate(paths)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["DistributionId"] == DISTRIBUTION_ID

    batch = call["InvalidationBatch"]
    # The rewritten cache key (/u/{sha}/index.html) is purged with a matching
    # Quantity — this is the URI the viewer-request rewrite caches under.
    assert batch["Paths"]["Items"] == ["/u/abc123/index.html"]
    assert batch["Paths"]["Quantity"] == 1
    assert batch["CallerReference"] == "ref-0"


def _rewrite_uri(uri: str) -> str:
    """Python mirror of ``REWRITE_FUNCTION_CODE`` in ``infra/cdn.ts``.

    The viewer-request CloudFront Function maps ``/u/{sha}`` and ``/u/{sha}/`` to
    ``/u/{sha}/index.html`` before the cache lookup, so the rewritten URI is the
    edge cache key. Replicated here so the regression test fails loudly if the
    infra rewrite and the backend invalidation path ever drift apart.
    """

    import re

    match = re.match(r"^/u/([^/]+)/?$", uri)
    if match:
        return f"/u/{match.group(1)}/index.html"
    return uri


def test_invalidation_path_matches_storage_key_and_rewrite_output() -> None:
    from share.storage import S3ObjectStorage

    sha = "deadbeef" * 8
    storage = S3ObjectStorage(
        client=None, private_bucket="private", public_bucket="public"
    )

    # The path purged is exactly the deleted object's key (/ + public_key) ...
    paths = invalidation_paths(storage.public_key(sha))
    assert paths == [f"/{storage.public_key(sha)}"]

    # ... and that is precisely what the viewer-request rewrite caches under for
    # BOTH viewer URL shapes, so the invalidation can never miss the edge entry.
    assert paths == [_rewrite_uri(f"/u/{sha}")]
    assert paths == [_rewrite_uri(f"/u/{sha}/")]
    assert paths == [f"/u/{sha}/index.html"]


def test_caller_reference_is_unique_per_batch() -> None:
    client = FakeCloudFrontClient()
    invalidator = _make(client)

    invalidator.invalidate(invalidation_paths("u/aaa/index.html"))
    invalidator.invalidate(invalidation_paths("u/bbb/index.html"))

    refs = [c["InvalidationBatch"]["CallerReference"] for c in client.calls]
    assert refs == ["ref-0", "ref-1"]
    assert len(set(refs)) == len(refs)


def test_empty_paths_skips_the_api_call() -> None:
    client = FakeCloudFrontClient()
    _make(client).invalidate([])
    assert client.calls == []


def test_client_error_becomes_unpublish_failed() -> None:
    invalidator = _make(BrokenCloudFrontClient())
    with pytest.raises(UnpublishFailedError):
        invalidator.invalidate(invalidation_paths("u/abc123/index.html"))


def test_get_invalidator_is_null_without_a_distribution_id() -> None:
    _cloudfront_invalidator.cache_clear()
    settings = Settings(cloudfront_distribution_id="")
    assert isinstance(_select(settings), NullInvalidator)


def test_get_invalidator_is_cloudfront_when_configured() -> None:
    _cloudfront_invalidator.cache_clear()
    settings = Settings(cloudfront_distribution_id=DISTRIBUTION_ID)
    invalidator = _select(settings)
    assert isinstance(invalidator, CloudFrontInvalidator)
    _cloudfront_invalidator.cache_clear()


def _select(settings: Settings):
    """Run ``get_invalidator`` against a specific Settings via get_settings override."""

    import share.publish.dependencies as deps

    original = deps.get_settings
    deps.get_settings = lambda: settings  # type: ignore[assignment]
    try:
        return get_invalidator()
    finally:
        deps.get_settings = original  # type: ignore[assignment]
