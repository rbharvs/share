import { cn, splitForMiddleTruncate } from "@/lib/utils";

/**
 * macOS Finder-style middle truncation: "my-long-quarterly-fin…port-final.pdf".
 *
 * Pure CSS — the head flexes and clips with an ellipsis while the tail is pinned
 * and never shrinks, so the extension stays visible at any width. The full name
 * is exposed via `title` (hover) and `aria-label` (screen readers); the visible
 * head/tail spans are split so no character is duplicated when read aloud.
 */
export function MiddleTruncate({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  const { head, tail } = splitForMiddleTruncate(name);
  return (
    <span
      dir="ltr"
      title={name}
      aria-label={name}
      className={cn("flex min-w-0 max-w-full items-center", className)}
    >
      <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
        {head}
      </span>
      <span aria-hidden className="flex-none whitespace-pre">
        {tail}
      </span>
    </span>
  );
}
