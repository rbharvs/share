import { ApiError, finalizeUpload, presignUpload } from "@/lib/api";
import type { ContentItem, PresignResponse, SourceType } from "@/lib/types";

/**
 * Maximum accepted upload size, in bytes (5 MB). Mirrors the backend
 * `MAX_UPLOAD_BYTES`; both presign's S3 policy and finalize's head-gate enforce
 * the same cap server-side. The client check here is purely for an immediate,
 * friendly rejection before any network round-trip.
 */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

/** Progress callback: `loaded`/`total` bytes for the S3 upload leg. */
export type ProgressFn = (progress: { loaded: number; total: number }) => void;

/**
 * Upload the raw file bytes directly to S3 via the presigned POST.
 *
 * This leg uses `XMLHttpRequest` (not `fetch`) for the sole reason that it
 * exposes upload-progress events, which drive the progress bar. The presigned
 * `fields` MUST be appended before the `file` part — S3 ignores form fields that
 * appear after the file. A non-2xx (e.g. the policy's content-length-range
 * rejecting an oversized file) surfaces as an {@link ApiError}.
 */
export function uploadToS3(
  presign: PresignResponse,
  file: File,
  onProgress?: ProgressFn,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [key, value] of Object.entries(presign.fields)) {
      form.append(key, value);
    }
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", presign.url, true);

    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = (event: ProgressEvent) => {
        onProgress({
          loaded: event.loaded,
          total: event.lengthComputable ? event.total : file.size,
        });
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(
          new ApiError(
            "The file upload was rejected by storage. It may be too large.",
            { code: "upload_rejected", status: xhr.status },
          ),
        );
      }
    };
    xhr.onerror = () => {
      reject(
        new ApiError("The file upload failed. Check your connection.", {
          code: "network_error",
          status: 0,
        }),
      );
    };
    xhr.onabort = () => {
      reject(
        new ApiError("The file upload was cancelled.", {
          code: "upload_aborted",
          status: 0,
        }),
      );
    };

    xhr.send(form);
  });
}

/**
 * Run the full upload flow for one file: presign → direct-to-S3 (with progress)
 * → finalize, resolving to the new immutable content item.
 *
 * `sourceType` is the resolved (inferred or owner-overridden) type sent to
 * presign so the backend stores it verbatim; an oversized file is rejected
 * locally with the same `upload_too_large` code the backend would return.
 */
export async function runUpload(
  file: File,
  sourceType: SourceType,
  onProgress?: ProgressFn,
): Promise<ContentItem> {
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new ApiError(
      `File is too large. The limit is ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB.`,
      { code: "upload_too_large", status: 0 },
    );
  }

  const presign = await presignUpload({
    filename: file.name,
    content_type: file.type || null,
    source_type: sourceType,
  });

  await uploadToS3(presign, file, onProgress);

  return finalizeUpload(presign.upload_id);
}
