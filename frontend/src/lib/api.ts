import type {
  ApiErrorBody,
  ContentListResponse,
} from "@/lib/types";

/**
 * A structured dashboard API error, carrying the backend's stable `code` and
 * the `request_id` so the UI can surface both the human message and a support
 * reference. Thrown for any non-2xx response from the dashboard API.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly requestId: string | null;
  readonly status: number;

  constructor(
    message: string,
    opts: { code?: string; requestId?: string | null; status: number },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = opts.code ?? "unknown_error";
    this.requestId = opts.requestId ?? null;
    this.status = opts.status;
  }
}

async function parseErrorBody(response: Response): Promise<ApiErrorBody> {
  try {
    return (await response.json()) as ApiErrorBody;
  } catch {
    return {};
  }
}

/**
 * Fetch one newest-first page of the content library.
 *
 * Uses only a relative `/api/*` URL (never an absolute host) and stores no
 * credentials — authentication is supplied out-of-band by Cloudflare Access (or
 * the local proxy) as a header the browser never sees. Non-2xx responses are
 * decoded into a structured {@link ApiError}.
 */
export async function fetchContent(
  cursor?: string | null,
): Promise<ContentListResponse> {
  const params = new URLSearchParams();
  if (cursor) params.set("cursor", cursor);
  const query = params.toString();
  const url = query ? `/api/content?${query}` : "/api/content";

  let response: Response;
  try {
    response = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      // Same-origin: the Access cookie/headers ride along; no tokens in JS.
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError("Could not reach the server. Check your connection.", {
      code: "network_error",
      status: 0,
    });
  }

  if (!response.ok) {
    const body = await parseErrorBody(response);
    throw new ApiError(
      body.error?.message ?? `Request failed (HTTP ${response.status}).`,
      {
        code: body.error?.code,
        requestId: body.error?.request_id ?? null,
        status: response.status,
      },
    );
  }

  return (await response.json()) as ContentListResponse;
}
