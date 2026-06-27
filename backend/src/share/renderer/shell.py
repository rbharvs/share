"""The self-contained HTML document shell wrapped around rendered Markdown.

Only Markdown output is wrapped: HTML uploads are emitted byte-for-byte and
never see this shell. The shell is a full, standalone document with a small
embedded stylesheet (no external requests, no scripts) so a rendered artifact
opens correctly from any origin or from ``file://``. The ``<title>`` is the
caller-supplied original filename, HTML-escaped so a hostile filename cannot
break out of the title element.

The template is a pure constant string formatted deterministically: identical
inputs always produce identical bytes, which is what keeps the golden tests
byte-stable.
"""

from __future__ import annotations

from html import escape

#: Minimal, dependency-free stylesheet. Intentionally small and stable — it is
#: part of the golden-tested output and is reviewed like code.
_STYLE = """\
:root { color-scheme: light dark; }
body {
  margin: 0 auto;
  max-width: 44rem;
  padding: 2rem 1.25rem;
  font: 16px/1.6 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}
h1, h2, h3, h4, h5, h6 { line-height: 1.25; }
pre, code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
pre {
  overflow: auto;
  padding: 0.75rem 1rem;
  background: rgba(127, 127, 127, 0.12);
  border-radius: 6px;
}
code { font-size: 0.95em; }
pre code { padding: 0; background: none; }
table { border-collapse: collapse; }
th, td { border: 1px solid rgba(127, 127, 127, 0.4); padding: 0.4rem 0.6rem; }
blockquote {
  margin: 0;
  padding-left: 1rem;
  border-left: 4px solid rgba(127, 127, 127, 0.4);
  color: inherit;
}
img { max-width: 100%; }
"""

#: The document template. ``{title}`` and ``{body}`` are the only holes.
_DOCUMENT = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{style}</style>
</head>
<body>
{body}
</body>
</html>
"""


def wrap_document(body_html: str, *, title: str) -> str:
    """Wrap rendered body HTML in the standalone document shell.

    ``title`` is HTML-escaped; ``body_html`` is inserted verbatim because the
    Markdown renderer intentionally preserves raw/unsafe HTML.
    """

    return _DOCUMENT.format(
        title=escape(title, quote=True),
        style=_STYLE,
        body=body_html.rstrip("\n"),
    )
