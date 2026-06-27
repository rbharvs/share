/** The two finalized source types the service supports (mirrors `SourceType`). */
export type SourceType = "html" | "markdown";

/** Mirrors the backend `ContentItemResponse` (the common content-item shape). */
export interface ContentItem {
  sha256: string;
  short_sha: string;
  source_type: string;
  original_filename: string;
  size_bytes: number;
  status: "uploaded" | "published" | "unpublished";
  created_at: string;
  updated_at: string;
  published_at: string | null;
  /** Always present — private content requires auth, the URL is not a secret. */
  private_url: string;
  /** Present only when the item is published. */
  public_url: string | null;
}

/** Mirrors the backend `ContentListResponse` (newest-first page + cursor). */
export interface ContentListResponse {
  items: ContentItem[];
  next_cursor: string | null;
}

/** Dashboard `POST /api/uploads/presign` request body. */
export interface PresignRequestBody {
  filename: string;
  content_type?: string | null;
  /** Explicit owner override; when omitted the backend infers from filename. */
  source_type?: SourceType | null;
  title?: string | null;
}

/**
 * Mirrors the backend `PresignResponse`: the opaque presigned S3 POST the
 * browser submits directly (multipart) to upload the file bytes.
 */
export interface PresignResponse {
  upload_id: string;
  url: string;
  fields: Record<string, string>;
  max_size_bytes: number;
}

/** The structured API error envelope: `{ error: { code, message, request_id } }`. */
export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    request_id?: string | null;
  };
}
