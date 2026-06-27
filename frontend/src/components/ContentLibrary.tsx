import { ExternalLink, Loader2 } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { ApiError, publishContent, unpublishContent } from "@/lib/api";
import type { ContentItem } from "@/lib/types";
import { formatBytes, formatTimestamp } from "@/lib/utils";
import type { Library } from "@/hooks/useLibrary";

/** A private/public content link, or an em dash when the link is absent. */
function ContentLink({
  href,
  label,
}: {
  href: string | null;
  label: string;
}) {
  if (!href) {
    return <span className="text-slate-400 dark:text-slate-600">—</span>;
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline dark:text-blue-400"
    >
      {label}
      <ExternalLink className="h-3 w-3" aria-hidden />
    </a>
  );
}

/**
 * The per-item publish / unpublish control.
 *
 * Calls the slice-08 idempotent APIs and replaces the item in place with the
 * returned content item, so status + public link update without a refetch. The
 * button is disabled while a request is in flight, which (together with the
 * backend's idempotency) makes a double-click a no-op.
 */
function PublishActions({
  item,
  onChanged,
}: {
  item: ContentItem;
  onChanged: (item: ContentItem) => void;
}) {
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();
  const published = item.status === "published";

  const mutate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const updated = published
        ? await unpublishContent(item.sha256)
        : await publishContent(item.sha256);
      onChanged(updated);
      toast({
        variant: "success",
        title: published
          ? `Unpublished ${updated.original_filename}`
          : `Published ${updated.original_filename}`,
        description: published
          ? "The public link has been removed."
          : "The public link is live.",
      });
    } catch (err) {
      const apiError = err instanceof ApiError ? err : null;
      toast({
        variant: "error",
        title: published ? "Unpublish failed" : "Publish failed",
        description:
          apiError?.message ??
          (err instanceof Error ? err.message : "Something went wrong."),
        code: apiError?.code,
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      variant={published ? "outline" : "default"}
      size="sm"
      disabled={busy}
      onClick={() => void mutate()}
    >
      {busy && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
      {published ? "Unpublish" : "Publish"}
    </Button>
  );
}

/**
 * The newest-first content library — the dashboard's first real view.
 *
 * Renders each item with filename / type / size / status / timestamps, the
 * always-present private link, the public link only when published, and a
 * publish/unpublish action. The list itself is owned by {@link Library} so
 * uploads prepend and mutations replace one shared source of truth (no polling).
 */
export function ContentLibrary({ library }: { library: Library }) {
  const { items, cursor, state, error, load, replace } = library;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Library</CardTitle>
        <CardDescription>
          Your uploaded content, newest first.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {state === "error" && items.length === 0 ? (
          <ErrorState error={error} onRetry={() => void load(null)} />
        ) : state === "loading" ? (
          <div className="flex items-center gap-2 py-8 text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading library…
          </div>
        ) : items.length === 0 ? (
          <div className="py-8 text-center text-sm text-slate-500">
            No content yet. Uploads will appear here.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Filename</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Size</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Updated</TableHead>
                <TableHead>Private link</TableHead>
                <TableHead>Public link</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.sha256}>
                  <TableCell>
                    <span className="font-medium" title={item.sha256}>
                      {item.original_filename}
                    </span>
                    <div className="font-mono text-xs text-slate-400">
                      {item.short_sha}
                    </div>
                  </TableCell>
                  <TableCell className="uppercase text-xs text-slate-500">
                    {item.source_type}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {formatBytes(item.size_bytes)}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={item.status} />
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs text-slate-500">
                    {formatTimestamp(item.created_at)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs text-slate-500">
                    {formatTimestamp(item.updated_at)}
                  </TableCell>
                  <TableCell>
                    <ContentLink href={item.private_url} label="Private" />
                  </TableCell>
                  <TableCell>
                    <ContentLink href={item.public_url} label="Public" />
                  </TableCell>
                  <TableCell>
                    <PublishActions item={item} onChanged={replace} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        {state === "error" && items.length > 0 && (
          <ErrorState error={error} onRetry={() => void load(cursor)} />
        )}

        {cursor && state !== "error" && (
          <div>
            <Button
              variant="outline"
              size="sm"
              disabled={state === "loading-more"}
              onClick={() => void load(cursor)}
            >
              {state === "loading-more" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : null}
              Load more
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
