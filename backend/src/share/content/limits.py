"""Shared upload size limit.

The 5 MB cap is enforced at TWO points that must stay in sync:

1. The presign policy ``content-length-range`` condition (slice 04) — rejected by
   S3 at upload time.
2. The finalize ``head_object`` gate (slice 05) — rejected *before* download.

Both import this single constant so the two gates can never drift apart.
"""

from __future__ import annotations

#: Maximum accepted upload size, in bytes (5 MB).
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5242880
