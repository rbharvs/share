#!/usr/bin/env python3
"""Reproducible single-zip Lambda packaging for the ``share`` backend.

This is the deep module behind ``mise run build``. It turns the working app into one
self-contained Lambda deployment artifact — no Lambda layers, no Docker — that
Pulumi (slice 13) consumes as a prebuilt input, so ``pulumi preview`` never does
expensive build work.

The zip is assembled at the *zip root* so that, on Lambda, ``sys.path`` resolves
both the vendored third-party packages and the first-party ``share`` package
(handler ``share.handler.handler``):

    lambda.zip
      share/...                 first-party package, incl. built SPA in static/
      fastapi/ pydantic/ ...     vendored runtime deps
      cryptography/ cffi/ ...    incl. the native arm64 wheel for pyjwt[crypto]
      requirements.txt          pinned manifest the deps were vendored from

The one real risk this retires is the native ``cryptography`` dependency
introduced by auth (slice 02): it ships a compiled extension, so the wheel must
match the Lambda runtime (Python 3.12 / ARM64), not the build host (macOS). We
fetch the correct wheel cross-platform via ``uv pip install --python-platform``;
the resulting ``.so`` files are AArch64 ELF objects, validated by the package
tests against a real zip.

The functions are intentionally small and individually testable; ``main`` only
wires them together for the CLI.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

#: Repo layout, anchored to this file so the build is independent of the caller's
#: working directory.
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"

#: The first-party ``share`` package. Its ``static/`` subdir is where the built
#: SPA is copied, so vendoring the package also vendors the SPA.
PACKAGE_SRC = BACKEND_DIR / "src" / "share"
STATIC_DIR = PACKAGE_SRC / "static"

#: Pinned, hash-free requirements export (committed for provenance + CI), and the
#: gitignored staging/output locations.
REQUIREMENTS = BACKEND_DIR / "src" / "requirements.txt"
STAGE_DIR = BACKEND_DIR / "build" / "lambda"
DEFAULT_ZIP = BACKEND_DIR / "dist" / "lambda.zip"

#: Lambda target: Python 3.12 on ARM64 (Amazon Linux). The ``manylinux2014``
#: aarch64 platform tag is forward-compatible with the AL2023 runtime and is the
#: tag the published ``cryptography`` arm64 wheels carry.
LAMBDA_PYTHON_VERSION = "3.12"
LAMBDA_PLATFORM = "aarch64-manylinux2014"

_EXCLUDE_DIRS = frozenset({"__pycache__"})
_EXCLUDE_SUFFIXES = (".pyc", ".pyo")
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def _run(cmd: list[str], *, cwd: Path) -> None:
    """Run ``cmd`` in ``cwd``, streaming output and raising on failure."""

    print(f"$ {' '.join(cmd)}  (cwd={cwd})", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def export_requirements(out: Path = REQUIREMENTS) -> Path:
    """Regenerate the pinned, dev-free requirements export from ``uv.lock``.

    ``--no-dev`` drops the ``dev`` dependency group, ``--no-emit-project`` omits
    the local ``share`` package (it is vendored separately), and ``--no-hashes``
    keeps the file consumable by ``uv pip install`` for a cross-platform target.
    """

    rel = out.relative_to(BACKEND_DIR)
    _run(
        [
            "uv",
            "export",
            "--no-dev",
            "--no-hashes",
            "--no-emit-project",
            "-o",
            str(rel),
        ],
        cwd=BACKEND_DIR,
    )
    return out


def vendor_dependencies(
    stage: Path,
    requirements: Path = REQUIREMENTS,
    *,
    platform: str = LAMBDA_PLATFORM,
    python_version: str = LAMBDA_PYTHON_VERSION,
) -> None:
    """Install the pinned deps into ``stage`` for the *Lambda* platform.

    ``--python-platform`` / ``--python-version`` resolve wheels for the Lambda
    runtime rather than the build host, and ``--only-binary :all:`` forces wheels
    so a wrong-platform sdist can never be silently compiled for the host.
    """

    _run(
        [
            "uv",
            "pip",
            "install",
            "-r",
            str(requirements),
            "--target",
            str(stage),
            "--python-platform",
            platform,
            "--python-version",
            python_version,
            "--only-binary",
            ":all:",
        ],
        cwd=BACKEND_DIR,
    )


def stage_package(stage: Path) -> None:
    """Copy the first-party ``share`` package (incl. built SPA) into ``stage``."""

    dest = stage / "share"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PACKAGE_SRC, dest, ignore=_COPY_IGNORE)


def write_zip(stage: Path, output: Path, requirements: Path = REQUIREMENTS) -> Path:
    """Deterministically zip ``stage`` (sorted) plus the requirements manifest."""

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(stage.rglob("*")):
            if path.is_dir():
                continue
            if _EXCLUDE_DIRS.intersection(path.parts):
                continue
            if path.suffix in _EXCLUDE_SUFFIXES:
                continue
            zf.write(path, path.relative_to(stage).as_posix())
        zf.write(requirements, "requirements.txt")
    return output


def build_frontend() -> None:
    """Build the Vite SPA and copy the bundle into the package ``static/`` dir.

    Mirrors the Makefile ``frontend-build`` target so a standalone invocation of
    this script also produces a complete artifact.
    """

    _run(["npm", "run", "build"], cwd=FRONTEND_DIR)
    if STATIC_DIR.exists():
        shutil.rmtree(STATIC_DIR)
    STATIC_DIR.mkdir(parents=True)
    dist = FRONTEND_DIR / "dist"
    for item in dist.iterdir():
        target = STATIC_DIR / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def build_lambda_zip(
    *,
    output: Path = DEFAULT_ZIP,
    build_frontend_first: bool = True,
    platform: str = LAMBDA_PLATFORM,
    python_version: str = LAMBDA_PYTHON_VERSION,
) -> Path:
    """Produce the single Lambda zip end-to-end and return its path."""

    if build_frontend_first:
        build_frontend()
    export_requirements()
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)
    STAGE_DIR.mkdir(parents=True)
    vendor_dependencies(
        STAGE_DIR, platform=platform, python_version=python_version
    )
    stage_package(STAGE_DIR)
    return write_zip(STAGE_DIR, output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_ZIP, help="zip output path"
    )
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="assume the SPA is already built into the package (Makefile does it)",
    )
    parser.add_argument("--platform", default=LAMBDA_PLATFORM)
    parser.add_argument("--python-version", default=LAMBDA_PYTHON_VERSION)
    args = parser.parse_args(argv)

    zip_path = build_lambda_zip(
        output=args.output,
        build_frontend_first=not args.skip_frontend,
        platform=args.platform,
        python_version=args.python_version,
    )
    size_mib = zip_path.stat().st_size / 1_048_576
    print(f"Built Lambda artifact: {zip_path} ({size_mib:.1f} MiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
