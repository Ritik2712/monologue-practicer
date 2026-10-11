import { Button } from "@/components/Button";

import { formatClock } from "../format";
import type { PracticeAction } from "../practiceStore";
import type { PracticeStep, PracticeSummary, TimerState } from "../types";

type TimerPanelProps = {
  activeStep: PracticeStep | null;
  activeStepNumber: number | null;
  timer: TimerState;
  remainingMs: number;
  summary: PracticeSummary;
  dispatch: (action: PracticeAction) => void;
};

const TIMER_LABELS: Record<TimerState["status"], string> = {
  idle: "Ready",
  running: "Running",
  paused: "Paused",
};

export function TimerPanel({
  activeStep,
  activeStepNumber,
  timer,
  remainingMs,
  summary,
  dispatch,
}: TimerPanelProps) {
  const paused = timer.status === "paused";

  return (
    <section
      aria-labelledby="timer-heading"
      className="rounded-lg border border-zinc-200 p-4 sm:p-6 dark:border-zinc-800"
    >
      <h2 id="timer-heading" className="text-sm font-medium text-zinc-600 dark:text-zinc-400">
        Current step
      </h2>

      {activeStep ? (
        <>
          <p className="mt-1 text-lg font-semibold">
            {activeStepNumber}. {activeStep.title}
          </p>
          <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            {/* No live region here: a screen reader would otherwise read out every second. */}
            <p
              role="timer"
              aria-label={`Time remaining: ${formatClock(remainingMs)}`}
              className="font-mono text-5xl font-semibold tabular-nums tracking-tight sm:text-6xl"
            >
              {formatClock(remainingMs)}
            </p>
            <p className="text-sm text-zinc-600 dark:text-zinc-400">{TIMER_LABELS[timer.status]}</p>
          </div>
        </>
      ) : (
        <p className="mt-1 text-lg font-semibold">
          {summary.routineCompleted
            ? `Routine complete: all ${summary.total} steps done today.`
            : `No steps left today. ${summary.completed} completed, ${summary.skipped} skipped.`}
        </p>
      )}
      {!activeStep && !summary.routineCompleted && (
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          To go back to a skipped step, choose “Do this step now” on it below.
        </p>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
        <Button
          variant={timer.status === "idle" ? "primary" : "secondary"}
          disabled={!activeStep || timer.status !== "idle"}
          onClick={() => dispatch({ type: "start" })}
        >
          Start
        </Button>
        <Button
          variant={paused ? "primary" : "secondary"}
          disabled={timer.status === "idle"}
          onClick={() => dispatch({ type: paused ? "resume" : "pause" })}
        >
          {paused ? "Resume" : "Pause"}
        </Button>
        <Button
          disabled={timer.status === "idle"}
          onClick={() => dispatch({ type: "reset_step" })}
        >
          Reset step
        </Button>
        <Button disabled={!activeStep} onClick={() => dispatch({ type: "skip_step" })}>
          Skip step
        </Button>
      </div>
    </section>
  );
}
