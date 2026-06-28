import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-none border border-retro-line text-sm font-medium shadow-hard transition-[transform,box-shadow,background-color,filter] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-retro-line focus-visible:ring-offset-2 focus-visible:ring-offset-retro-bg motion-safe:active:translate-x-[2px] motion-safe:active:translate-y-[2px] active:shadow-none disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-retro-accent text-retro-accent-fg hover:brightness-95",
        outline: "bg-retro-surface text-retro-ink hover:bg-retro-bg",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3 text-xs",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
);
Button.displayName = "Button";
