"use client";

import { Button } from "@/components/Button";

import { COACH_STATUS_TEXT, coachHelp } from "../coaching";
import type { HealthState } from "../healthMonitor";
import { Command, Notice } from "./parts";

/** Says plainly when a part of the local backend that analysis needs is missing. */
export function BackendNotice({ health, onCheckAgain }: { health: HealthState; onCheckAgain: () => void }) {
  const again = <Button onClick={onCheckAgain}>Check again</Button>;
  if (health.status === "checking") return null;
  if (health.status === "unreachable") {
    return (
      <Notice kind="warning" action={again}>
        The local backend is not running, so nothing can be analysed yet. In a terminal, run:
        <Command>cd backend && uv run uvicorn app.main:app --port 8000</Command>
      </Notice>
    );
  }
  const { database, worker, speechModel } = health.health;
  if (database !== "ok") {
    return (
      <Notice kind="warning" action={again}>
        The backend cannot use its database. In a terminal, run:
        <Command>cd backend && uv run alembic upgrade head</Command>
      </Notice>
    );
  }
  if (worker !== "running") {
    return (
      <Notice kind="warning" action={again}>
        The analysis worker is not running. You can submit a recording, but it will wait in the
        queue until the worker starts. In a terminal, run:
        <Command>cd backend && uv run python -m app.worker</Command>
      </Notice>
    );
  }
  if (speechModel === "missing") {
    return (
      <Notice kind="warning" action={again}>
        The speech model is not downloaded, so analyses will fail. Download it once (about 480
        MB):
        <Command>cd backend && uv run python -m app.speech_model download</Command>
      </Notice>
    );
  }
  const { coach, coachModel } = health.health;
  if (coach !== "ready" && coach !== "unknown" && coach !== "off") {
    // Not a blocker: everything is still measured, and coaching falls back to fixed rules.
    const help = coachHelp(coach, coachModel);
    return (
      <Notice kind="info" action={again}>
        AI coaching is not available: {COACH_STATUS_TEXT[coach]}. Recordings are still measured
        in full, and the coaching is written from fixed rules instead. {help?.text}
        {help?.command && <Command>{help.command}</Command>}
      </Notice>
    );
  }
  return null;
}
