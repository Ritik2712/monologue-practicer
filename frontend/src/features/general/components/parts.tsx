/** Small pieces shared by the General Practice components. */
import type { ReactNode } from "react";

import { QUALITY_LABELS } from "../format";
import type { MetricValue, Quality } from "../types";

export const FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:focus-visible:outline-indigo-400";

export const MUTED = "text-zinc-600 dark:text-zinc-400";

const QUALITY_STYLES: Record<Quality, string> = {
  measured: "border-zinc-300 text-zinc-700 dark:border-zinc-700 dark:text-zinc-300",
  estimated: "border-amber-400 text-amber-900 dark:border-amber-700 dark:text-amber-200",
  unavailable: "border-zinc-300 text-zinc-600 dark:border-zinc-700 dark:text-zinc-400",
};

/** Says in words how far a number can be trusted. Only shown when it is not plainly measured. */
export function QualityBadge({ quality }: { quality: Quality }) {
  if (quality === "measured") return null;
  return (
    <span className={`rounded-full border px-1.5 py-0.5 text-[11px] font-medium ${QUALITY_STYLES[quality]}`}>
      {QUALITY_LABELS[quality]}
    </span>
  );
}

/** Marks a measurement that the chosen delivery profile depends on most. */
export function FocusTag() {
  return (
    <span className="rounded-full bg-indigo-100 px-1.5 py-0.5 text-[11px] font-medium text-indigo-900 dark:bg-indigo-950 dark:text-indigo-200">
      Profile focus
    </span>
  );
}

type TileProps = {
  label: string;
  value: string;
  unit?: string;
  metric?: MetricValue;
  /** One line under the value: the formula, or what the number means. */
  hint?: ReactNode;
  /** Marks a measurement the chosen delivery profile depends on most. */
  focus?: boolean;
  children?: ReactNode;
};

/** One headline number: label, value, and a line saying what it is. */
export function Tile({ label, value, unit, metric, hint, focus, children }: TileProps) {
  const unavailable = metric?.quality === "unavailable";
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className={`text-sm ${MUTED}`}>{label}</p>
        {metric && <QualityBadge quality={metric.quality} />}
        {focus && <FocusTag />}
      </div>
      <p className="mt-1 text-2xl font-semibold">
        {value}
        {unit && !unavailable && <span className={`ml-1 text-sm font-normal ${MUTED}`}>{unit}</span>}
      </p>
      {children}
      {(hint || (unavailable && metric?.note)) && (
        <p className={`mt-1 text-xs ${MUTED}`}>{unavailable && metric?.note ? metric.note : hint}</p>
      )}
    </div>
  );
}

export function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <div>
        <h3 id={id} className="text-lg font-semibold">
          {title}
        </h3>
        {description && <p className={`mt-1 text-sm ${MUTED}`}>{description}</p>}
      </div>
      {children}
    </section>
  );
}

/** A text-style button for actions inside tables and lists. */
export function LinkButton({
  className = "",
  ...rest
}: React.ComponentPropsWithoutRef<"button">) {
  return (
    <button
      type="button"
      className={`rounded px-1 py-1.5 text-sm font-medium text-indigo-800 underline underline-offset-4 hover:no-underline disabled:cursor-not-allowed disabled:text-zinc-500 disabled:no-underline dark:text-indigo-300 dark:disabled:text-zinc-500 ${FOCUS_RING} ${className}`}
      {...rest}
    />
  );
}

export function Notice({
  kind,
  children,
  action,
}: {
  kind: "info" | "warning" | "error";
  children: ReactNode;
  action?: ReactNode;
}) {
  const styles = {
    info: "border-zinc-200 dark:border-zinc-800",
    warning: "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100",
    error: "border-red-300 bg-red-50 text-red-950 dark:border-red-900 dark:bg-red-950 dark:text-red-100",
  }[kind];
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      className={`flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm ${styles}`}
    >
      <div className="min-w-0 flex-1">{children}</div>
      {action}
    </div>
  );
}

/** A terminal command the user is asked to run. */
export function Command({ children }: { children: string }) {
  return (
    <code className="mt-1 block overflow-x-auto rounded bg-black/5 px-2 py-1 font-mono text-xs whitespace-pre dark:bg-white/10">
      {children}
    </code>
  );
}
