// @vitest-environment happy-dom
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLibrary } from "@/hooks/useLibrary";
import type { ContentItem, ContentListResponse } from "@/lib/types";

// The hook's only data source is fetchContent(cursor); mock it so we drive the
// cursor pagination behavior deterministically (the real DynamoDB cursor walk is
// covered by the backend test_list_content.py suite).
vi.mock("@/lib/api", () => ({ fetchContent: vi.fn() }));
import { fetchContent } from "@/lib/api";

const mockFetch = vi.mocked(fetchContent);

function mkItem(sha: string): ContentItem {
  return {
    sha256: sha,
    short_sha: sha.slice(0, 8),
    source_type: "html",
    original_filename: `${sha}.html`,
    size_bytes: 100,
    status: "uploaded",
    created_at: "2026-06-27T00:00:00Z",
    updated_at: "2026-06-27T00:00:00Z",
    published_at: null,
    private_url: `https://private/${sha}`,
    public_url: null,
  };
}

function page(shas: string[], next_cursor: string | null): ContentListResponse {
  return { items: shas.map(mkItem), next_cursor };
}

const shasOf = (items: ContentItem[]) => items.map((i) => i.sha256);

afterEach(() => vi.clearAllMocks());

describe("useLibrary cursor pagination", () => {
  it("loads the first page on mount and exposes the next cursor", async () => {
    mockFetch.mockResolvedValueOnce(page(["a", "b"], "cur1"));

    const { result } = renderHook(() => useLibrary());

    await waitFor(() => expect(result.current.state).toBe("ready"));
    expect(shasOf(result.current.items)).toEqual(["a", "b"]);
    expect(result.current.cursor).toBe("cur1");
    expect(mockFetch).toHaveBeenCalledWith(null);
  });

  it("appends the next page without overlap and clears the cursor at the end", async () => {
    mockFetch
      .mockResolvedValueOnce(page(["a", "b"], "cur1"))
      .mockResolvedValueOnce(page(["c", "d"], null));

    const { result } = renderHook(() => useLibrary());
    await waitFor(() => expect(result.current.cursor).toBe("cur1"));

    await act(async () => {
      await result.current.load("cur1");
    });

    // Page 2 is appended after page 1 (no overlap, order preserved).
    expect(shasOf(result.current.items)).toEqual(["a", "b", "c", "d"]);
    // next_cursor=null means no more pages -> the "Load more" affordance hides.
    expect(result.current.cursor).toBeNull();
    expect(mockFetch).toHaveBeenLastCalledWith("cur1");
  });

  it("reports loading-more (not loading) while a subsequent page is in flight", async () => {
    let resolveSecond!: () => void;
    mockFetch.mockResolvedValueOnce(page(["a"], "cur1")).mockReturnValueOnce(
      new Promise<ContentListResponse>((resolve) => {
        resolveSecond = () => resolve(page(["b"], null));
      }),
    );

    const { result } = renderHook(() => useLibrary());
    await waitFor(() => expect(result.current.state).toBe("ready"));

    act(() => {
      void result.current.load("cur1");
    });
    await waitFor(() => expect(result.current.state).toBe("loading-more"));

    await act(async () => {
      resolveSecond();
    });
    await waitFor(() => expect(result.current.state).toBe("ready"));
    expect(shasOf(result.current.items)).toEqual(["a", "b"]);
  });

  it("surfaces a fetch error while keeping the already-loaded page", async () => {
    mockFetch.mockResolvedValueOnce(page(["a"], "cur1")).mockRejectedValueOnce(new Error("boom"));

    const { result } = renderHook(() => useLibrary());
    await waitFor(() => expect(result.current.state).toBe("ready"));

    await act(async () => {
      await result.current.load("cur1");
    });

    expect(result.current.state).toBe("error");
    expect(result.current.error).toBeInstanceOf(Error);
    // The failed append does not drop the items already shown.
    expect(shasOf(result.current.items)).toEqual(["a"]);
    // cursor is retained so the user can retry the same page.
    expect(result.current.cursor).toBe("cur1");
  });
});
