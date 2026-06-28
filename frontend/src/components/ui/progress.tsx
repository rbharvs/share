import { cn } from "@/lib/utils";

/**
 * A determinate progress bar (0–100). Used for the direct-to-S3 upload leg,
 * whose byte-progress is reported by the XHR `upload.onprogress` events.
 */
export function Progress({ value, className }: { value: number; className?: string }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div
      className={cn(
        "h-2 w-full overflow-hidden rounded-none border border-retro-line bg-retro-bg",
        className,
      )}
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className="h-full rounded-none bg-retro-accent transition-all duration-150"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
