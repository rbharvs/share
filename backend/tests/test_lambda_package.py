"""Validates the single Lambda zip produced by ``scripts/build_lambda.py``.

These tests build a *real* zip (vendoring deps for the Lambda platform) and
assert its observable shape: the first-party package + built SPA are present, the
native ``cryptography`` dependency is the ARM64 wheel (not the build host's), and
dev/test-only tooling is excluded. They retire the one real risk this slice
carries — that the native ``cryptography`` arm64 wheel resolves for Lambda.

The build shells out to ``uv``; it is skipped when ``uv`` is unavailable.
"""

from __future__ import annotations

import importlib.util
import shutil
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: AArch64 (the Lambda ARM64 target) in the ELF ``e_machine`` field.
_EM_AARCH64 = 0xB7


def _load_build_module():
    path = REPO_ROOT / "scripts" / "build_lambda.py"
    spec = importlib.util.spec_from_file_location("share_build_lambda", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lambda_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("uv") is None:
        pytest.skip("uv is required to build the Lambda zip")

    build = _load_build_module()

    # Simulate the frontend build output so the package carries an SPA without a
    # node toolchain. Track what we create so we leave the tree as we found it.
    static: Path = build.STATIC_DIR
    static.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    index = static / "index.html"
    if not index.exists():
        index.write_text("<!doctype html><title>share</title>", encoding="utf-8")
        created.append(index)
    assets = static / "assets"
    assets.mkdir(exist_ok=True)
    sentinel = assets / "pkgtest-app.js"
    sentinel.write_text("// spa sentinel", encoding="utf-8")
    created.append(sentinel)

    out = tmp_path_factory.mktemp("artifact") / "lambda.zip"
    try:
        build.build_lambda_zip(output=out, build_frontend_first=False)
    finally:
        for f in created:
            f.unlink(missing_ok=True)
    return out


@pytest.fixture(scope="module")
def names(lambda_zip: Path) -> list[str]:
    with zipfile.ZipFile(lambda_zip) as zf:
        return zf.namelist()


def test_zip_contains_first_party_package(names: list[str]) -> None:
    assert "share/handler.py" in names
    assert "share/api/app.py" in names
    assert "share/__init__.py" in names


def test_zip_contains_built_spa_assets(names: list[str]) -> None:
    assert "share/static/index.html" in names
    assert "share/static/assets/pkgtest-app.js" in names


def test_zip_includes_pinned_requirements_manifest(
    lambda_zip: Path, names: list[str]
) -> None:
    assert "requirements.txt" in names
    with zipfile.ZipFile(lambda_zip) as zf:
        manifest = zf.read("requirements.txt").decode()
    assert "cryptography==" in manifest
    # dev/test tooling must not leak into the runtime manifest.
    assert "pytest" not in manifest
    assert "moto" not in manifest


def test_zip_vendors_cryptography_for_arm64(lambda_zip: Path, names: list[str]) -> None:
    assert any(n.startswith("cryptography/") for n in names), "cryptography missing"

    so_names = [n for n in names if n.endswith(".so")]
    assert so_names, "expected native extension modules in the vendored deps"

    with zipfile.ZipFile(lambda_zip) as zf:
        for name in so_names:
            head = zf.read(name)[:20]
            assert head[:4] == b"\x7fELF", f"{name} is not an ELF object"
            e_machine = int.from_bytes(head[18:20], "little")
            assert e_machine == _EM_AARCH64, (
                f"{name} is built for machine 0x{e_machine:02x}, not AArch64 "
                f"(0x{_EM_AARCH64:02x}); wrong-platform wheel vendored"
            )


def test_zip_excludes_dev_dependencies_and_bytecode(names: list[str]) -> None:
    assert not any(n.startswith("pytest/") for n in names)
    assert not any(n.startswith("moto/") for n in names)
    assert not any(n.startswith("ruff") for n in names)
    assert not any("__pycache__" in n for n in names)
    assert not any(n.endswith(".pyc") for n in names)
