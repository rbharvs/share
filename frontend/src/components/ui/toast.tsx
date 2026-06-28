import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";

type ToastVariant = "success" | "error";

interface Toast {
  id: number;
  title: string;
  description?: string;
  /** Stable backend error code, shown monospace for support reference. */
  code?: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  /** Push a transient toast; returns nothing (fire-and-forget). */
  toast: (toast: Omit<Toast, "id">) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const AUTO_DISMISS_MS = 6000;

/**
 * A minimal, dependency-free toast system. Errors surface the structured API
 * `code` + `message` here (per the slice's "no polling — toasts" requirement);
 * successes confirm uploads/publishes. Toasts auto-dismiss but can be closed.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = nextId.current++;
      setToasts((prev) => [...prev, { ...toast, id }]);
      window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.variant === "error" ? "alert" : "status"}
            className={cn(
              "pointer-events-auto flex items-start gap-3 rounded-none border border-retro-line p-3 text-sm text-retro-ink shadow-hard-lg",
              t.variant === "error" ? "bg-retro-danger-weak" : "bg-retro-accent-weak",
            )}
          >
            {t.variant === "error" ? (
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            ) : (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            )}
            <div className="flex-1">
              <div className="font-medium">{t.title}</div>
              {t.description && <div className="mt-0.5 opacity-90">{t.description}</div>}
              {t.code && <div className="mt-1 font-mono text-xs opacity-70">{t.code}</div>}
            </div>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              className="shrink-0 opacity-60 hover:opacity-100"
              aria-label="Dismiss"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** Access the toast pusher; must be used under a {@link ToastProvider}. */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}
