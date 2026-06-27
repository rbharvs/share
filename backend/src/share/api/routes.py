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

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from share.hosts import HostKind

router = APIRouter()


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


@router.api_route("/u/{sha}", methods=["GET", "HEAD"], include_in_schema=False)
async def private_content(sha: str) -> HTMLResponse:
    # Placeholder until the renderer + storage land (slices 03/05/07).
    return HTMLResponse(f"<!doctype html><title>content {sha}</title>")
