"""Static SPA serving for the dashboard host.

This is the deep module behind the dashboard's SPA / asset / robots surface. The
built Vite bundle is copied into ``src/share/static`` at build time (gitignored);
the same FastAPI process serves it locally (``make preview``) and on Lambda, so
production and preview exercise byte-identical serving code.

Precedence falls out naturally: the SPA history fallback runs only in the 404
handler (:func:`share.api.app._maybe_spa_fallback`), i.e. *after* routing has
found no concrete match. So every registered route — the whole API surface,
``/assets/{path}``, ``/robots.txt``, ``/u/{sha}`` — takes precedence over the
fallback, and ``/api/*`` / ``/assets/*`` are excluded there so an unknown API
route or missing asset stays ``route_not_allowed`` rather than returning the SPA.

When the bundle has not been built into the package (fresh checkout, CI without a
frontend build) the site degrades gracefully: the dashboard host still answers
``200`` with a placeholder shell so the request spine and host gate remain fully
exercised without a frontend build.

Asset URLs emitted by Vite are root-absolute (``/assets/...``), not relative to
the document, so the SPA served at ``/`` resolves its assets correctly without
any trailing-slash ``307`` shim — the habit-tracker shim the issue asks about is
deliberately NOT needed here, and none is added to the Mangum wrapper.
"""

from __future__ import annotations

from pathlib import Path

from starlette.responses import FileResponse, HTMLResponse, Response

#: Where the build copies the compiled Vite bundle (``frontend/dist/*``). This
#: directory is gitignored and absent until a build runs.
BUNDLED_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

#: Served on the dashboard host when no bundle has been built yet, so the host
#: gate / request spine stay demoable without a frontend build. Contains the
#: word "dashboard" so the walking-skeleton host tests keep passing pre-build.
_PLACEHOLDER_INDEX = (
    "<!doctype html><html><head><title>share dashboard</title></head>"
    "<body><main>share dashboard — SPA bundle not built; run "
    "<code>make preview</code> or <code>npm run build</code>.</main></body></html>"
)


class StaticSite:
    """Serves the built dashboard SPA, its assets, and the SPA fallback.

    A thin, pure adapter over a directory of built files. It performs no host
    gating itself (the host gate runs first) and never serves outside its root.
    """

    def __init__(self, root: Path = BUNDLED_STATIC_DIR) -> None:
        self._root = root

    @property
    def built(self) -> bool:
        """True once a real ``index.html`` bundle is present in the package."""

        return (self._root / "index.html").is_file()

    def index_response(self) -> Response:
        """The dashboard document: the built ``index.html`` or the placeholder.

        ``Cache-Control: no-store`` keeps the history-fallback HTML uncached so a
        deploy is picked up immediately; the hashed assets it references are
        themselves immutable and cached by URL.
        """

        index = self._root / "index.html"
        if index.is_file():
            return FileResponse(
                index,
                media_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        return HTMLResponse(_PLACEHOLDER_INDEX, headers={"Cache-Control": "no-store"})

    def asset_response(self, rel_path: str) -> Response | None:
        """A built asset under ``/assets/{rel_path}``, or ``None`` if absent.

        ``None`` lets the route fall back to a placeholder before a build exists;
        once built, a missing asset is a genuine 404 (returned as ``None`` too,
        which the route maps to ``route_not_allowed``).
        """

        if not self.built:
            return None
        target = self._safe_join(self._root / "assets", rel_path)
        if target is None or not target.is_file():
            return None
        return FileResponse(target)

    def root_file_response(self, name: str) -> Response | None:
        """A single top-level bundled file (``favicon.ico``, ``vite.svg``, ...).

        Only a bare filename is accepted (no nested paths, no ``index.html``), so
        the SPA fallback can serve Vite's root assets without ever leaking
        ``index.html`` or traversing the tree.
        """

        if not self.built or "/" in name or name in ("", "index.html"):
            return None
        target = self._safe_join(self._root, name)
        if target is None or not target.is_file():
            return None
        return FileResponse(target)

    @staticmethod
    def _safe_join(base: Path, rel_path: str) -> Path | None:
        """Resolve ``base/rel_path`` and reject anything escaping ``base``."""

        base = base.resolve()
        candidate = (base / rel_path).resolve()
        if candidate == base or base in candidate.parents:
            return candidate
        return None
