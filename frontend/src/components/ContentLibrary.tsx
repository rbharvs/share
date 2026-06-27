import { ExternalLink, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

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
import { fetchContent } from "@/lib/api";
import type { ContentItem } from "@/lib/types";
import { formatBytes, formatTimestamp } from "@/lib/utils";

type LoadState = "idle" | "loading" | "loading-more" | "error" | "ready";

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
 * The newest-first content library — the dashboard's first real view.
 *
 * Loads `GET /api/content` on mount (no polling, per the PRD), renders each item
 * with filename / type / size / status / timestamps, the always-present private
 * link, and the public link only when published. Cursor pagination drives an
 * explicit "Load more". Structured API errors are surfaced verbatim.
 */
export function ContentLibrary() {
  const [items, setItems] = useState<ContentItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async (nextCursor: string | null) => {
    setState(nextCursor ? "loading-more" : "loading");
    setError(null);
    try {
      const page = await fetchContent(nextCursor);
      setItems((prev) => (nextCursor ? [...prev, ...page.items] : page.items));
      setCursor(page.next_cursor);
      setState("ready");
    } catch (err) {
      setError(err);
      setState("error");
    }
  }, []);

  useEffect(() => {
    void load(null);
  }, [load]);

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
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.sha256}>
                  <TableCell>
                    <span
                      className="font-medium"
                      title={item.sha256}
                    >
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
