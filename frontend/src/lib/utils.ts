import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn/ui class combiner: merge conditional + conflicting Tailwind classes. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Human-readable byte size (binary units), e.g. 1536 -> "1.5 KiB". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

/**
 * Split a filename into a `head` (clipped with an ellipsis at render time) and a
 * `tail` that always retains the extension — for macOS Finder-style middle
 * truncation ("long-report…-final.pdf").
 *
 * The tail length floats between `minTail` and `maxTail` and, where possible,
 * begins just after a separator (`- _ . space`) so it shows a whole trailing
 * token + extension ("…variant-b.html") rather than a mid-word slice
 * ("…t-b.html"). When no clean boundary lands in that window it falls back to a
 * fixed-length tail. Dotfiles and extensionless names get a plain tail.
 */
export function splitForMiddleTruncate(
  name: string,
  { minTail = 8, maxTail = 18 }: { minTail?: number; maxTail?: number } = {},
): { head: string; tail: string } {
  const dot = name.lastIndexOf(".");
  // dot <= 0 means no extension (or a dotfile like ".env"): plain tail.
  const extLen = dot > 0 ? name.length - dot : 0;
  // The tail must always cover the extension plus a few leading chars.
  const lower = Math.min(name.length, Math.max(minTail, extLen + 3));
  const upper = Math.min(name.length, Math.max(lower, maxTail));
  const isSep = (c: string) => c === "-" || c === "_" || c === "." || c === " ";

  // Prefer the longest token-aligned tail within [lower, upper]; the loop walks
  // from the long-tail end so the first hit is the most context-rich boundary.
  let splitAt = name.length - lower;
  for (let i = name.length - upper; i <= name.length - lower; i++) {
    if (i > 0 && isSep(name[i - 1]) && !isSep(name[i])) {
      splitAt = i;
      break;
    }
  }
  return { head: name.slice(0, splitAt), tail: name.slice(splitAt) };
}

/** Render an ISO timestamp as a stable local date-time, or em dash if absent. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
