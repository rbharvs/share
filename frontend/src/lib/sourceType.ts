import type { SourceType } from "@/lib/types";

/**
 * Client-side source-type inference, mirroring the backend `SourceType.infer`
 * precedence (filename extension first, then declared MIME). It exists only to
 * pre-fill the visible override control with a sensible default; the backend
 * re-derives and is the source of truth. When nothing matches we return `null`
 * so the UI can require an explicit override before upload rather than guessing.
 */

/** The selectable source types, in display order, for the override control. */
export const SOURCE_TYPES: readonly SourceType[] = ["html", "markdown"];

/** Human labels for the override control. */
export const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  html: "HTML",
  markdown: "Markdown",
};

const EXTENSION_HINTS: Record<string, SourceType> = {
  html: "html",
  htm: "html",
  md: "markdown",
  markdown: "markdown",
};

const MIME_HINTS: Record<string, SourceType> = {
  "text/html": "html",
  "application/xhtml+xml": "html",
  "text/markdown": "markdown",
  "text/x-markdown": "markdown",
};

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  if (dot < 0 || dot === filename.length - 1) return "";
  return filename
    .slice(dot + 1)
    .trim()
    .toLowerCase();
}

/**
 * Infer a source type from a filename and optional MIME type, or `null` when
 * neither yields a supported type (e.g. a `.txt` file the owner must override).
 */
export function inferSourceType(filename: string, mimeType?: string | null): SourceType | null {
  const ext = extensionOf(filename);
  if (ext in EXTENSION_HINTS) return EXTENSION_HINTS[ext];

  if (mimeType) {
    const mime = mimeType.split(";", 1)[0]?.trim().toLowerCase() ?? "";
    if (mime in MIME_HINTS) return MIME_HINTS[mime];
  }
  return null;
}
