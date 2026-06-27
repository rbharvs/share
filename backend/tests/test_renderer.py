"""Behavior + golden tests for the content renderer.

The renderer is the one place private-preview and public output are produced, so
these tests pin both its *exact bytes* (goldens, reviewed like code) and its
externally observable guarantees: HTML byte-passthrough and Markdown unsafe/raw
preservation.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

from share.content import SourceType
from share.errors import UnsupportedSourceTypeError
from share.renderer import (
    HtmlPassthroughRenderer,
    MarkdownShellRenderer,
    render,
)


class HTMLSnapshotExtension(SingleFileSnapshotExtension):
    """One reviewable ``.html`` file per golden, diffed like source."""

    file_extension = "html"
    _write_mode = WriteMode.TEXT


@pytest.fixture
def snapshot_html(snapshot):
    return snapshot.use_extension(HTMLSnapshotExtension)


# A deliberately hostile HTML upload: arbitrary scripts, inline handlers, and a
# javascript: URL. Every byte must survive untouched.
HTML_UPLOAD = (
    b"<!doctype html>\n"
    b"<html><head><title>uploader's own title</title></head>\n"
    b"<body>\n"
    b"<h1>Interactive</h1>\n"
    b'<script>document.title = "rewritten by js";</script>\n'
    b'<button onclick="alert(1)">click</button>\n'
    b'<a href="javascript:alert(2)">link</a>\n'
    b"</body></html>\n"
)

MARKDOWN_UPLOAD = (
    b"# Heading\n"
    b"\n"
    b"A paragraph with <b>raw inline HTML</b> and a "
    b'<a href="javascript:alert(1)">javascript URL</a> plus an '
    b'<span onclick="steal()">onclick span</span>.\n'
    b"\n"
    b'<div class="raw-block">A raw HTML block.</div>\n'
    b"\n"
    b"| Fruit | Qty |\n"
    b"| ----- | --- |\n"
    b"| Apple | 3   |\n"
    b"| Pear  | 7   |\n"
    b"\n"
    b"- [x] shipped\n"
    b"- [ ] pending\n"
    b"\n"
    b"~~struck through~~\n"
)


# --------------------------------------------------------------------------- #
# HTML: exact byte passthrough
# --------------------------------------------------------------------------- #
def test_html_artifact_bytes_equal_raw_exactly() -> None:
    out = render(HTML_UPLOAD, SourceType.HTML, title="ignored.html")
    assert out == HTML_UPLOAD  # byte-for-byte, no sanitize/wrap/inject
    assert isinstance(out, bytes)


def test_html_artifact_golden(snapshot_html) -> None:
    out = render(HTML_UPLOAD, SourceType.HTML, title="demo.html")
    assert out.decode("utf-8") == snapshot_html


def test_html_title_is_never_injected() -> None:
    # HTML carries its own <title>; the caller's title must not change a byte.
    a = render(HTML_UPLOAD, SourceType.HTML, title="alpha.html")
    b = render(HTML_UPLOAD, SourceType.HTML, title="beta.html")
    assert a == b == HTML_UPLOAD


def test_html_passthrough_renderer_returns_same_object() -> None:
    out = HtmlPassthroughRenderer().render(HTML_UPLOAD, title="x")
    assert out == HTML_UPLOAD


# --------------------------------------------------------------------------- #
# Markdown: shell + unsafe/raw preservation
# --------------------------------------------------------------------------- #
def test_markdown_golden(snapshot_html) -> None:
    out = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="notes.md")
    assert out.decode("utf-8") == snapshot_html


def test_markdown_uses_filename_as_title() -> None:
    out = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="my-notes.md").decode()
    assert "<title>my-notes.md</title>" in out


def test_markdown_renders_full_document() -> None:
    out = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="d.md").decode()
    assert out.startswith("<!doctype html>")
    assert "<html" in out and "</html>" in out
    assert '<meta charset="utf-8">' in out


def test_markdown_preserves_raw_html() -> None:
    out = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="d.md").decode()
    assert "<b>raw inline HTML</b>" in out
    assert '<div class="raw-block">A raw HTML block.</div>' in out


def test_markdown_preserves_javascript_urls() -> None:
    out = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="d.md").decode()
    assert 'href="javascript:alert(1)"' in out


def test_markdown_preserves_onclick_attributes() -> None:
    out = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="d.md").decode()
    assert 'onclick="steal()"' in out


def test_markdown_renders_tables() -> None:
    out = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="d.md").decode()
    assert "<table>" in out
    assert "<th>Fruit</th>" in out
    assert "<td>Apple</td>" in out


def test_markdown_renders_task_lists() -> None:
    out = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="d.md").decode()
    assert 'type="checkbox"' in out
    assert "checked" in out  # the [x] item


def test_markdown_renders_strikethrough() -> None:
    out = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="d.md").decode()
    assert "<del>struck through</del>" in out


def test_markdown_title_is_html_escaped() -> None:
    # A hostile filename must not break out of the <title> element.
    hostile = "</title><script>alert(1)</script>"
    out = render(b"# hi", SourceType.MARKDOWN, title=hostile).decode()
    assert "<title>&lt;/title&gt;&lt;script&gt;" in out
    assert "<title></title><script>alert(1)" not in out


def test_markdown_title_only_changes_the_title() -> None:
    # Title comes only from the caller; same body + different title differ only
    # in the <title> line, nowhere else.
    a = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="one.md").decode()
    b = render(MARKDOWN_UPLOAD, SourceType.MARKDOWN, title="two.md").decode()
    pairs = zip(a.splitlines(), b.splitlines(), strict=True)
    diff = [(x, y) for x, y in pairs if x != y]
    assert diff == [("<title>one.md</title>", "<title>two.md</title>")]


def test_markdown_output_is_utf8_bytes() -> None:
    out = render("# café — naïve ☕\n".encode(), SourceType.MARKDOWN, title="u.md")
    assert isinstance(out, bytes)
    assert "café — naïve ☕" in out.decode("utf-8")


def test_markdown_shell_renderer_directly() -> None:
    out = MarkdownShellRenderer().render(b"# direct\n", title="z.md")
    assert b"<title>z.md</title>" in out
    assert b"<h1>direct</h1>" in out


# --------------------------------------------------------------------------- #
# Source-type schema primitive
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("html", SourceType.HTML),
        ("HTML", SourceType.HTML),
        (" markdown ", SourceType.MARKDOWN),
        ("markdown", SourceType.MARKDOWN),
    ],
)
def test_source_type_parse_accepts_supported(value, expected) -> None:
    assert SourceType.parse(value) is expected


@pytest.mark.parametrize("value", ["pdf", "text", "", "htm", "md"])
def test_source_type_parse_rejects_unsupported(value) -> None:
    with pytest.raises(UnsupportedSourceTypeError) as exc:
        SourceType.parse(value)
    assert exc.value.code == "unsupported_source_type"
    assert exc.value.status_code == 415


# --------------------------------------------------------------------------- #
# Purity guard: zero AWS / IO imports
# --------------------------------------------------------------------------- #
_FORBIDDEN_IMPORT_ROOTS = {
    "boto3",
    "botocore",
    "aws_lambda_powertools",
    "mangum",
    "os",
    "io",
    "pathlib",
    "socket",
    "requests",
    "urllib",
    "httpx",
    "subprocess",
}


def _imported_roots(source: str) -> set[str]:
    roots: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_renderer_package_has_zero_aws_or_io_imports() -> None:
    import share.renderer as pkg

    pkg_dir = pathlib.Path(pkg.__file__).parent
    for py in pkg_dir.glob("*.py"):
        roots = _imported_roots(py.read_text(encoding="utf-8"))
        offending = roots & _FORBIDDEN_IMPORT_ROOTS
        assert not offending, f"{py.name} imports forbidden modules: {offending}"
