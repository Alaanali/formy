/** Small shared primitives. Deliberately not a component library: the app
 *  has a handful of shapes and a dependency would cost more than it saves. */

import type { ReactNode } from "react";

type Tone = "accent" | "danger" | "ok" | "warn" | "neutral";

const TONE_CHIP: Record<Tone, string> = {
  accent: "bg-accent-soft text-accent ring-1 ring-accent-line/50",
  danger: "bg-danger-soft text-danger ring-1 ring-danger/25",
  ok: "bg-ok-soft text-ok ring-1 ring-ok/25",
  warn: "bg-warn-soft text-warn ring-1 ring-warn/25",
  neutral: "bg-line-soft text-muted ring-1 ring-line",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CHIP[tone]}`}
    >
      {children}
    </span>
  );
}

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
}) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium " +
    "transition-[background-color,border-color,color,box-shadow,transform] duration-150 " +
    "active:translate-y-px disabled:opacity-45 disabled:cursor-not-allowed " +
    "disabled:active:translate-y-0";
  const sizes = { sm: "px-2.5 py-1 text-sm", md: "px-3.5 py-2 text-sm" };
  const variants = {
    primary: "bg-accent text-white shadow-card hover:bg-accent-hover",
    secondary: "border border-line bg-surface text-ink shadow-card hover:bg-raised",
    ghost: "text-muted hover:bg-line-soft hover:text-ink",
    danger: "bg-danger text-white shadow-card hover:brightness-110",
  };
  return (
    <button
      className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
      {...props}
    />
  );
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-line bg-surface shadow-card ${className}`}
    >
      {children}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted" role="status">
      <span
        aria-hidden
        className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-accent"
      />
      {label}
    </div>
  );
}

export function ErrorBanner({
  title = "Something went wrong",
  message,
  details,
  onRetry,
}: {
  title?: string;
  message?: string;
  details?: string[];
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-danger/30 bg-danger-soft p-3.5 text-sm"
    >
      <p className="font-medium text-danger">{title}</p>
      {message && <p className="mt-1 text-ink-soft">{message}</p>}
      {details && details.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-ink-soft">
          {details.map((detail) => (
            <li key={detail}>{detail}</li>
          ))}
        </ul>
      )}
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-2.5" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-surface/40 px-6 py-12 text-center">
      <p className="font-medium">{title}</p>
      {body && <p className="mx-auto mt-1.5 max-w-md text-sm text-muted">{body}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function Labelled({
  label,
  hint,
  error,
  required,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium">
        {label}
        {required && (
          <span className="ml-1 text-danger" aria-label="required">
            *
          </span>
        )}
      </label>
      {hint && <p className="text-xs text-muted">{hint}</p>}
      {children}
      {error && (
        <p role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export const inputClass =
  "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink " +
  "transition-colors placeholder:text-faint hover:border-faint " +
  "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25";

/** Selects and other native controls that should match `inputClass`. */
export const controlClass =
  "rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-ink " +
  "transition-colors hover:border-faint focus:border-accent focus:outline-none " +
  "focus:ring-2 focus:ring-accent/25";

export function StatusBadge({ status }: { status: string }) {
  const tone: Tone =
    status === "published" || status === "completed" || status === "ready"
      ? "ok"
      : status === "draft" || status === "in_progress" || status === "pending"
        ? "warn"
        : status === "failed"
          ? "danger"
          : "neutral";
  return <Badge tone={tone}>{status.replace(/_/g, " ")}</Badge>;
}

/** Up/down reordering. A pair of buttons rather than drag-and-drop: it works
 *  with a keyboard and a screen reader, which dragging does not. */
export function MoveButtons({
  onUp,
  onDown,
  canUp,
  canDown,
  label,
  index,
}: {
  onUp: () => void;
  onDown: () => void;
  canUp: boolean;
  canDown: boolean;
  label: string;
  index?: number;
}) {
  const style =
    "flex h-6 w-6 items-center justify-center rounded-md text-muted transition-colors " +
    "hover:bg-line-soft hover:text-ink disabled:opacity-30 disabled:hover:bg-transparent";
  return (
    <div className="flex flex-col">
      <button type="button" className={style} onClick={onUp} disabled={!canUp} aria-label={`Move ${label} up`}>
        <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M8 12.5v-9M4 7.5 8 3.5l4 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {index !== undefined && (
        <span className="text-center text-[11px] font-medium leading-none tabular-nums text-faint">
          {index}
        </span>
      )}
      <button type="button" className={style} onClick={onDown} disabled={!canDown} aria-label={`Move ${label} down`}>
        <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M8 3.5v9M4 8.5l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  );
}

/** "Saving… / Saved / failed", shared by the builder and the respondent form. */
export function SaveState({ saving, dirty, error }: { saving: boolean; dirty: boolean; error?: string }) {
  if (error) return <span className="text-xs font-medium text-danger">{error}</span>;
  if (saving) return <span className="text-xs text-muted">Saving…</span>;
  if (dirty) return <span className="text-xs text-muted">Unsaved…</span>;
  return (
    <span className="flex items-center gap-1 text-xs text-ok">
      <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="3">
        <path d="m5 12.5 4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Saved
    </span>
  );
}
