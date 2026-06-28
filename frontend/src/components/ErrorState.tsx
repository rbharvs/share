import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";

/**
 * Surfaces a structured API error: the human message plus the stable error
 * `code` and the `request_id` for support, exactly as the backend envelope
 * provides them. Falls back gracefully for non-API errors.
 */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const apiError = error instanceof ApiError ? error : null;
  const message =
    apiError?.message ?? (error instanceof Error ? error.message : "Something went wrong.");

  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-none border border-retro-line bg-retro-danger-weak p-4 text-sm text-retro-ink shadow-hard"
    >
      <div className="flex items-center gap-2 font-medium">
        <AlertTriangle className="h-4 w-4" aria-hidden />
        <span>{message}</span>
      </div>
      {apiError && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-xs text-retro-muted">
          <dt>code</dt>
          <dd>{apiError.code}</dd>
          {apiError.requestId && (
            <>
              <dt>request id</dt>
              <dd>{apiError.requestId}</dd>
            </>
          )}
        </dl>
      )}
      <Button variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}
