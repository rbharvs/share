import { Badge } from "@/components/ui/badge";
import type { ContentItem } from "@/lib/types";

const VARIANT: Record<ContentItem["status"], "success" | "muted" | "outline"> = {
  published: "success",
  uploaded: "outline",
  unpublished: "muted",
};

export function StatusBadge({ status }: { status: ContentItem["status"] }) {
  return <Badge variant={VARIANT[status] ?? "outline"}>{status}</Badge>;
}
