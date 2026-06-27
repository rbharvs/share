import { useCallback, useEffect, useState } from "react";

import { fetchContent } from "@/lib/api";
import type { ContentItem } from "@/lib/types";

export type LibraryState =
  | "idle"
  | "loading"
  | "loading-more"
  | "error"
  | "ready";

export interface Library {
  items: ContentItem[];
  cursor: string | null;
  state: LibraryState;
  error: unknown;
  /** (Re)load from the start, or append the next page when `cursor` is set. */
  load: (cursor: string | null) => Promise<void>;
  /** Insert a freshly finalized item at the top (newest-first). */
  prepend: (item: ContentItem) => void;
  /** Replace an item in place by SHA after a publish/unpublish mutation. */
  replace: (item: ContentItem) => void;
}

/**
 * Owns the content-library list so both the upload flow (which prepends new
 * items) and the per-row publish/unpublish actions (which replace items in
 * place) mutate exactly one source of truth. No polling — the list is loaded
 * once on mount and thereafter mutated locally from API responses.
 */
export function useLibrary(): Library {
  const [items, setItems] = useState<ContentItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [state, setState] = useState<LibraryState>("idle");
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

  const prepend = useCallback((item: ContentItem) => {
    setItems((prev) => [
      item,
      ...prev.filter((existing) => existing.sha256 !== item.sha256),
    ]);
  }, []);

  const replace = useCallback((item: ContentItem) => {
    setItems((prev) =>
      prev.map((existing) =>
        existing.sha256 === item.sha256 ? item : existing,
      ),
    );
  }, []);

  useEffect(() => {
    void load(null);
  }, [load]);

  return { items, cursor, state, error, load, prepend, replace };
}
