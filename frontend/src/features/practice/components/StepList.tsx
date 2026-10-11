import Link from "next/link";

import { PRACTICE_ROUTINE } from "../config";
import { formatClock, formatDuration } from "../format";
import type { PracticeAction } from "../practiceStore";
import type { DailyPracticeRecord, PracticeStep } from "../types";

type StepListProps = {
  record: DailyPracticeRecord;
  remainingMs: number;
  dispatch: (action: PracticeAction) => void;
};

const BADGE_BASE = "rounded-full px-2 py-0.5 text-xs font-medium";

export function StepList({ record, remainingMs, dispatch }: StepListProps) {
  return (
    <ol className="flex flex-col gap-3">
      {record.steps.map((step, index) => (
        <StepItem
          key={step.id}
          step={step}
          number={index + 1}
          active={step.id === record.activeStepId}
          // Only the current step counts down; the others show their planned length.
          clockMs={step.id === record.activeStepId ? remainingMs : step.durationSeconds * 1000}
          dispatch={dispatch}
        />
      ))}
    </ol>
  );
}

type StepItemProps = {
  step: PracticeStep;
  number: number;
  active: boolean;
  clockMs: number;
  dispatch: (action: PracticeAction) => void;
};

function StepItem({ step, number, active, clockMs, dispatch }: StepItemProps) {
  const config = PRACTICE_ROUTINE.steps.find((candidate) => candidate.id === step.id);
  const checkboxId = `practice-step-${step.id}`;
  const completed = step.status === "completed";
  const skipped = step.status === "skipped";

  return (
    <li
      aria-current={active ? "step" : undefined}
      className={`rounded-lg border p-4 ${
        active
          ? "border-indigo-600 bg-indigo-50 dark:border-indigo-400 dark:bg-indigo-950/40"
          : "border-zinc-200 dark:border-zinc-800"
      }`}
    >
      <div className="flex items-start gap-3">
        <input
          id={checkboxId}
          type="checkbox"
          checked={completed}
          onChange={(event) =>
            dispatch({ type: "set_completed", stepId: step.id, completed: event.target.checked })
          }
          className="mt-1 h-5 w-5 shrink-0 accent-indigo-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:accent-indigo-400 dark:focus-visible:outline-indigo-400"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <label
              htmlFor={checkboxId}
              className={`font-semibold ${completed ? "text-zinc-600 line-through dark:text-zinc-400" : ""}`}
            >
              {number}. {step.title}
            </label>
            {active && (
              <span className={`${BADGE_BASE} bg-indigo-700 text-white dark:bg-indigo-400 dark:text-zinc-950`}>
                Current step
              </span>
            )}
            {completed && (
              <span className={`${BADGE_BASE} bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200`}>
                Completed
              </span>
            )}
            {skipped && (
              <span className={`${BADGE_BASE} bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200`}>
                Skipped
              </span>
            )}
          </div>

          {config && (
            <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">{config.instruction}</p>
          )}
          {config?.link && (
            <p className="mt-1 text-sm">
              <Link
                href={config.link.href}
                className="rounded font-medium text-indigo-800 underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:text-indigo-300 dark:focus-visible:outline-indigo-400"
              >
                {config.link.label}
              </Link>
            </p>
          )}
          {config?.note && (
            <p className="mt-1 text-sm text-zinc-600 italic dark:text-zinc-400">{config.note}</p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
            <span className="text-zinc-600 dark:text-zinc-400">
              Planned: {formatDuration(step.durationSeconds)}
            </span>
            <span className="font-mono tabular-nums" aria-label={`Timer: ${formatClock(clockMs)}`}>
              {formatClock(clockMs)}
            </span>
            {!active && !completed && (
              <button
                type="button"
                onClick={() => dispatch({ type: "select_step", stepId: step.id })}
                aria-label={`${skipped ? "Do this step now" : "Make this the current step"}: ${step.title}`}
                className="rounded px-1 py-2 font-medium text-indigo-800 underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:text-indigo-300 dark:focus-visible:outline-indigo-400"
              >
                {skipped ? "Do this step now" : "Make current"}
              </button>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}
