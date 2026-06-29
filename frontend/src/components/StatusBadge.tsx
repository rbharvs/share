import { Badge } from "@/components/ui/badge";
import type { ContentItem } from "@/lib/types";

const VARIANT: Record<ContentItem["status"], "success" | "muted" | "outline"> = {
  published: "success",
  uploaded: "outline",
  unpublished: "muted",
};

export function StatusBadge({ status }: { status: ContentItem["status"] }) {
  // Fixed width + centered text so every status box is the same size regardless
  // of label length (matches the equal-width action buttons).
  return (
    <Badge variant={VARIANT[status] ?? "outline"} className="min-w-[7rem] justify-center">
      {status}
    </Badge>
  );
}
