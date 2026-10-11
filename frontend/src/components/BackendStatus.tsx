"use client";

import { useEffect, useState } from "react";

import { apiUrl } from "@/lib/api";

type Status = "checking" | "ok" | "degraded" | "unreachable";

const LABELS: Record<Status, string> = {
  checking: "Checking local backend…",
  ok: "Local backend is running",
  degraded: "Local backend is running, but its database check failed",
  unreachable: "Local backend is not reachable — start it with the command in the README",
};

const DOT_COLORS: Record<Status, string> = {
  checking: "bg-zinc-400",
  ok: "bg-emerald-600",
  degraded: "bg-amber-500",
  unreachable: "bg-red-600",
};

export function BackendStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const controller = new AbortController();
    fetch(apiUrl("/api/health"), { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((body: { status?: string }) => setStatus(body.status === "ok" ? "ok" : "degraded"))
      .catch(() => {
        if (!controller.signal.aborted) setStatus("unreachable");
      });
    return () => controller.abort();
  }, []);

  return (
    <p role="status" className="flex items-center gap-2 text-sm">
      <span aria-hidden="true" className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT_COLORS[status]}`} />
      {LABELS[status]}
    </p>
  );
}
