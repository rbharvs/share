"""Placeholder routes for the walking skeleton.

These are trivial endpoints that exercise the request spine end-to-end. Real
SPA serving, content APIs, and rendered-artifact delivery arrive in later
slices. Handlers vary placeholder content by ``request.state.host_kind`` (set
by the host-gate middleware) rather than re-reading the ``Host`` header.

Deliberately: there is NO ``DELETE`` route anywhere (story 23 by-absence). The
private content host only reaches ``/`` , ``/robots.txt`` and ``/u/{sha}``
because the gate rejects everything else with ``route_not_allowed`` before
routing.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from share.auth import Principal, require_principal
from share.content import ContentItemResponse, private_rendered_headers
from share.hosts import HostKind
from share.listing import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    ContentListResponse,
    ContentServiceDep,
)
from share.preview import PreviewServiceDep
from share.publish import PublishServiceDep
from share.security import require_csrf
from share.upload import (
    FinalizeRequest,
    PresignRequest,
    PresignResponse,
    UploadServiceDep,
)

router = APIRouter()

#: Authenticates the request against the dashboard Access app (slice 02).
_dashboard_principal = require_principal(HostKind.DASHBOARD)

#: Authenticates the request against the private-content Access app (slice 02).
#: A dashboard-audience token is rejected here because the audience differs.
_private_principal = require_principal(HostKind.PRIVATE_CONTENT)


def _host_kind(request: Request) -> HostKind:
    return getattr(request.state, "host_kind", HostKind.UNKNOWN)


@router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root(request: Request):
    if _host_kind(request) is HostKind.PRIVATE_CONTENT:
        return HTMLResponse("<!doctype html><title>private content host</title>")
    return HTMLResponse("<!doctype html><title>share dashboard</title>")


@router.get("/robots.txt", include_in_schema=False)
async def robots() -> PlainTextResponse:
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@router.get("/assets/{path:path}", include_in_schema=False)
async def assets(path: str) -> PlainTextResponse:
    # Placeholder until built Vite assets are mounted (slice 09).
    return PlainTextResponse(f"asset:{path}")


@router.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "share"})


@router.post("/api/uploads/presign", response_model=PresignResponse)
async def presign_upload(
    body: PresignRequest,
    service: UploadServiceDep,
    principal: Principal = Depends(_dashboard_principal),
    _csrf: None = Depends(require_csrf),
) -> PresignResponse:
    """Create an upload session and return a presigned S3 POST.

    Reached only on the dashboard host (the gate rejects it elsewhere). The
    verified ``principal`` supplies ``created_by``; ``require_csrf`` enforces the
    CSRF header + dashboard Origin before any state change.
    """

    return service.presign(body, principal)


@router.post("/api/uploads/finalize", response_model=ContentItemResponse)
async def finalize_upload(
    body: FinalizeRequest,
    service: UploadServiceDep,
    principal: Principal = Depends(_dashboard_principal),
    _csrf: None = Depends(require_csrf),
) -> ContentItemResponse:
    """Finalize a completed upload into an immutable content item.

    Reached only on the dashboard host (the gate rejects it elsewhere). Filename
    and source type come from the stored session, not ``body``; ``require_csrf``
    enforces the CSRF header + dashboard Origin before any state change.
    """

    return service.finalize(body, principal)


@router.get("/api/content", response_model=ContentListResponse)
async def list_content(
    service: ContentServiceDep,
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    cursor: str | None = Query(None),
    principal: Principal = Depends(_dashboard_principal),
) -> ContentListResponse:
    """List content newest-first with opaque-cursor pagination.

    Reached only on the dashboard host (the gate rejects it elsewhere) and only
    for the authenticated owner. A read-only GET, so no CSRF/Origin check; the
    ``principal`` gate is the authorization. ``limit`` defaults to 50 (capped at
    100); ``cursor`` resumes a prior page without scanning.
    """

    return service.list_content(limit=limit, cursor=cursor)


@router.post("/api/content/{sha}/publish", response_model=ContentItemResponse)
async def publish_content(
    sha: str,
    service: PublishServiceDep,
    principal: Principal = Depends(_dashboard_principal),
    _csrf: None = Depends(require_csrf),
) -> ContentItemResponse:
    """Publish (or republish/repair) the public copy of ``sha``.

    Reached only on the dashboard host (the gate rejects it elsewhere). Idempotent
    and self-reconciling: regenerates the public artifact from the canonical raw
    source, writes it to the public bucket, and atomically marks both metadata
    items ``published``. ``require_csrf`` enforces the CSRF header + dashboard
    Origin before any state change; an unknown SHA surfaces as ``content_not_found``.
    """

    return service.publish(sha)


@router.post("/api/content/{sha}/unpublish", response_model=ContentItemResponse)
async def unpublish_content(
    sha: str,
    service: PublishServiceDep,
    principal: Principal = Depends(_dashboard_principal),
    _csrf: None = Depends(require_csrf),
) -> ContentItemResponse:
    """Unpublish the public copy of ``sha``.

    Reached only on the dashboard host (the gate rejects it elsewhere). Deletes
    the public object (idempotent), computes the slash + no-slash CloudFront
    invalidation paths, and atomically marks both metadata items ``unpublished``.
    ``require_csrf`` enforces the CSRF header + dashboard Origin before any state
    change; an unknown SHA surfaces as ``content_not_found``.
    """

    return service.unpublish(sha)


@router.api_route("/u/{sha}", methods=["GET", "HEAD"], include_in_schema=False)
async def private_content(
    sha: str,
    request: Request,
    service: PreviewServiceDep,
    principal: Principal = Depends(_private_principal),
) -> Response:
    """Serve the authenticated private rendered artifact for ``sha``.

    Reached only on the private content host (the gate rejects ``/u/{sha}`` on
    the dashboard and never routes it on public). ``_private_principal`` requires
    a valid private-audience Access token, so a dashboard-audience token is
    rejected here. The artifact is wrapped in the CSP-sandbox header set (no
    ``allow-same-origin``) that isolates the arbitrary uploaded JS from the
    dashboard origin; a missing SHA surfaces as ``content_not_found``.

    ``HEAD`` returns the identical headers (including the real ``Content-Length``)
    with no body, resolving the size via an S3 ``HEAD`` so the artifact bytes are
    never read.
    """

    headers = private_rendered_headers()
    if request.method == "HEAD":
        headers["Content-Length"] = str(service.head_artifact(sha))
        return Response(status_code=200, headers=headers)
    return Response(content=service.get_artifact(sha), headers=headers)
