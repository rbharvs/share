import type {
  ApiErrorBody,
  ContentItem,
  ContentListResponse,
  PresignRequestBody,
  PresignResponse,
} from "@/lib/types";

/**
 * The custom header every state-changing dashboard request must carry. Its
 * presence — which a cross-origin page cannot set without a (deliberately
 * absent) CORS preflight — is what the backend's CSRF guard checks alongside the
 * browser-supplied `Origin`. The value is a fixed sentinel, not a secret.
 */
export const CSRF_HEADER = "X-Share-CSRF";
export const CSRF_TOKEN = "1";

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

/** Decode a non-2xx dashboard response into a structured {@link ApiError}. */
async function errorFromResponse(response: Response): Promise<ApiError> {
  const body = await parseErrorBody(response);
  return new ApiError(
    body.error?.message ?? `Request failed (HTTP ${response.status}).`,
    {
      code: body.error?.code,
      requestId: body.error?.request_id ?? null,
      status: response.status,
    },
  );
}

/**
 * Issue a state-changing dashboard JSON request.
 *
 * Every dashboard mutation rides `fetch` (not XHR — only the S3 upload needs
 * progress) and carries the `X-Share-CSRF: 1` header. The dashboard `Origin` is
 * attached automatically by the browser on this same-origin request and is a
 * forbidden header JS cannot set itself, so it is never set here. No credentials
 * or tokens are read from JS — Access supplies auth out-of-band.
 */
async function postDashboardJson<T>(
  url: string,
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        [CSRF_HEADER]: CSRF_TOKEN,
      },
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Could not reach the server. Check your connection.", {
      code: "network_error",
      status: 0,
    });
  }

  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  return (await response.json()) as T;
}

/**
 * Create an upload session and obtain a presigned S3 POST.
 *
 * First leg of the upload flow: the returned {@link PresignResponse} is handed
 * to {@link uploadToS3} (XHR, for progress), then {@link finalizeUpload} turns
 * the temp object into an immutable content item.
 */
export function presignUpload(
  body: PresignRequestBody,
): Promise<PresignResponse> {
  return postDashboardJson<PresignResponse>("/api/uploads/presign", body);
}

/**
 * Finalize a completed S3 upload into an immutable, SHA-addressed content item.
 *
 * The backend reads filename/source-type/title from the stored session, so the
 * body deliberately carries only the `upload_id`.
 */
export function finalizeUpload(uploadId: string): Promise<ContentItem> {
  return postDashboardJson<ContentItem>("/api/uploads/finalize", {
    upload_id: uploadId,
  });
}

/**
 * Publish (or republish/repair) the public copy of a content item.
 *
 * Idempotent on the backend, so a double-click is safe — it returns the updated
 * content item with `status: "published"` and a `public_url`.
 */
export function publishContent(sha256: string): Promise<ContentItem> {
  return postDashboardJson<ContentItem>(
    `/api/content/${encodeURIComponent(sha256)}/publish`,
  );
}

/**
 * Unpublish a content item, removing its public copy.
 *
 * Idempotent on the backend, so a double-click is safe — it returns the updated
 * content item with `status: "unpublished"` and a null `public_url`.
 */
export function unpublishContent(sha256: string): Promise<ContentItem> {
  return postDashboardJson<ContentItem>(
    `/api/content/${encodeURIComponent(sha256)}/unpublish`,
  );
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
    throw await errorFromResponse(response);
  }

  return (await response.json()) as ContentListResponse;
}
