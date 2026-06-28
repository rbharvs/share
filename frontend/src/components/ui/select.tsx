import { forwardRef, type SelectHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/**
 * A styled native `<select>`. Native is deliberate: it is accessible, keyboard-
 * friendly, and dependency-free, which is all the source-type override control
 * needs.
 */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "h-8 rounded-none border border-retro-line bg-retro-surface px-2 text-xs text-retro-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-retro-line focus-visible:ring-offset-1 focus-visible:ring-offset-retro-bg disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Select.displayName = "Select";
