"use client";

import { useState } from "react";

import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";

import { PRACTICE_ROUTINE } from "../config";
import { formatDayLabel, totalMinutes } from "../format";
import { getActiveStep, isPristine, summarize } from "../practiceState";
import type { StorageWarning } from "../practiceStore";
import { usePracticeChecklist } from "../usePracticeChecklist";
import { PracticeHistory } from "./PracticeHistory";
import { StepList } from "./StepList";
import { TimerPanel } from "./TimerPanel";

const ROUTINE_MINUTES = totalMinutes(PRACTICE_ROUTINE.steps.map((step) => step.durationSeconds));

const WARNING_TEXT: Record<StorageWarning, string> = {
  unavailable:
    "This browser is blocking local storage, so your progress will be lost when this page is closed or refreshed.",
  corrupt:
    "Saved checklist data on this device could not be read, so a fresh checklist was started.",
  partially_invalid: "Some saved practice days could not be read and have been left out.",
  write_failed: "Your latest progress could not be saved on this device. Storage may be full.",
};

const CONFIRMATIONS = {
  reset_today: {
    title: "Reset today's checklist?",
    description:
      "This clears today's completed and skipped steps and stops the timer. Previous days in your history are not affected.",
    confirmLabel: "Reset today",
  },
  clear_history: {
    title: "Clear practice history?",
    description:
      "This deletes the saved checklist records for previous days from this device. Today's checklist and the rest of the app are not affected. This cannot be undone.",
    confirmLabel: "Clear history",
  },
} as const;

type Confirmation = keyof typeof CONFIRMATIONS;

export function PracticeChecklist() {
  const { snapshot, dispatch } = usePracticeChecklist();
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  // Keeps the dialog's text in place while it closes.
  const [lastConfirmation, setLastConfirmation] = useState<Confirmation>("reset_today");

  const header = (
    <header>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Daily Speaking Practice</h1>
        <span className="rounded-full border border-zinc-300 px-3 py-1 text-sm font-medium dark:border-zinc-700">
          {ROUTINE_MINUTES}-minute routine
        </span>
      </div>
      <p className="mt-2 text-zinc-700 dark:text-zinc-300">
        {PRACTICE_ROUTINE.steps.length} timed steps for one monologue, in any language.
      </p>
    </header>
  );

  if (!snapshot) {
    return (
      <div className="flex flex-col gap-6">
        {header}
        <p role="status" className="text-zinc-600 dark:text-zinc-400">
          Loading your checklist…
        </p>
      </div>
    );
  }

  const { record, remainingMs, todayKey, warning } = snapshot;
  const summary = summarize(record);
  const activeStep = getActiveStep(record);
  const activeStepNumber = activeStep ? record.steps.indexOf(activeStep) + 1 : null;
  const finishingYesterday = record.localDate !== todayKey;

  const ask = (kind: Confirmation) => {
    setLastConfirmation(kind);
    setConfirmation(kind);
  };
  const confirm = () => {
    if (confirmation) dispatch({ type: confirmation });
    setConfirmation(null);
  };

  return (
    <div className="flex flex-col gap-6">
      {header}

      {warning && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100"
        >
          <p>{WARNING_TEXT[warning]}</p>
          <Button onClick={() => dispatch({ type: "dismiss_warning" })}>Dismiss</Button>
        </div>
      )}

      {finishingYesterday && (
        <p className="rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-800">
          This timer started before midnight, so it counts towards{" "}
          {formatDayLabel(record.localDate, todayKey).toLowerCase()}. A fresh checklist for today
          appears when it stops.
        </p>
      )}

      <section aria-labelledby="progress-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 id="progress-heading" className="text-lg font-semibold">
            {summary.completed} of {summary.total} steps completed
          </h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {summary.percent}%{summary.skipped > 0 && ` · ${summary.skipped} skipped`}
          </p>
        </div>
        <div
          role="progressbar"
          aria-labelledby="progress-heading"
          aria-valuemin={0}
          aria-valuemax={summary.total}
          aria-valuenow={summary.completed}
          aria-valuetext={`${summary.completed} of ${summary.total} steps completed`}
          className="mt-2 h-3 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
        >
          <div
            className="h-full rounded-full bg-emerald-600 transition-[width] dark:bg-emerald-500"
            style={{ width: `${summary.percent}%` }}
          />
        </div>
      </section>

      <TimerPanel
        activeStep={activeStep}
        activeStepNumber={activeStepNumber}
        timer={record.timer}
        remainingMs={remainingMs}
        summary={summary}
        dispatch={dispatch}
      />

      {/* Announces step changes to screen readers without reading out the countdown. */}
      <p aria-live="polite" className="sr-only">
        {summary.completed} of {summary.total} steps completed.{" "}
        {activeStep ? `Current step: ${activeStep.title}.` : "No current step."}
      </p>

      <section aria-labelledby="steps-heading" className="flex flex-col gap-3">
        <h2 id="steps-heading" className="text-lg font-semibold">
          Steps
        </h2>
        <StepList record={record} remainingMs={remainingMs} dispatch={dispatch} />
        <div>
          <Button
            variant="danger"
            disabled={isPristine(record)}
            onClick={() => ask("reset_today")}
          >
            Reset today&apos;s checklist
          </Button>
        </div>
      </section>

      <PracticeHistory snapshot={snapshot} onClearHistory={() => ask("clear_history")} />

      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        Your checklist and progress are saved only in this browser on this device. They do not
        sync anywhere, and clearing this browser&apos;s site data removes them.
      </p>

      <ConfirmDialog
        open={confirmation !== null}
        {...CONFIRMATIONS[confirmation ?? lastConfirmation]}
        onConfirm={confirm}
        onCancel={() => setConfirmation(null)}
      />
    </div>
  );
}
