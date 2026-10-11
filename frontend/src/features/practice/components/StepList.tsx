import type { ReactNode } from "react";

import { PRACTICE_ROUTINE } from "../config";
import { formatClock, formatDuration } from "../format";
import type { PracticeAction } from "../practiceStore";
import type { DailyPracticeRecord, PracticeStep } from "../types";

type StepListProps = {
  record: DailyPracticeRecord;
  remainingMs: number;
  dispatch: (action: PracticeAction) => void;
  /** What each step is done with, by step ID: the original to listen to, the recorder… */
  tools?: Record<string, ReactNode>;
  /** Whether a step's tools are showing. */
  isOpen?: (stepId: string) => boolean;
  onToggle?: (stepId: string, open: boolean) => void;
};

const BADGE_BASE = "rounded-full px-2 py-0.5 text-xs font-medium";
const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:focus-visible:outline-indigo-400";

/** Where a step's row is on the page, so another part of the page can scroll to it. */
export function stepElementId(stepId: string): string {
  return `practice-step-item-${stepId}`;
}

export function StepList({
  record,
  remainingMs,
  dispatch,
  tools = {},
  isOpen = () => false,
  onToggle = () => {},
}: StepListProps) {
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
          tools={tools[step.id]}
          open={isOpen(step.id)}
          onToggle={(open) => onToggle(step.id, open)}
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
  tools: ReactNode;
  open: boolean;
  onToggle: (open: boolean) => void;
};

function StepItem({ step, number, active, clockMs, dispatch, tools, open, onToggle }: StepItemProps) {
  const config = PRACTICE_ROUTINE.steps.find((candidate) => candidate.id === step.id);
  const checkboxId = `practice-step-${step.id}`;
  const toolsId = `practice-step-tools-${step.id}`;
  const completed = step.status === "completed";
  const skipped = step.status === "skipped";
  const hasTools = tools !== undefined && tools !== null;

  return (
    <li
      id={stepElementId(step.id)}
      aria-current={active ? "step" : undefined}
      className={`scroll-mt-4 rounded-lg border p-4 ${
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
          className={`mt-1 h-5 w-5 shrink-0 accent-indigo-700 dark:accent-indigo-400 ${FOCUS}`}
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
                className={`rounded px-1 py-2 font-medium text-indigo-800 underline underline-offset-4 hover:no-underline dark:text-indigo-300 ${FOCUS}`}
              >
                {skipped ? "Do this step now" : "Make current"}
              </button>
            )}
            {hasTools && (
              <button
                type="button"
                aria-expanded={open}
                aria-controls={toolsId}
                onClick={() => onToggle(!open)}
                className={`rounded px-1 py-2 font-medium text-indigo-800 underline underline-offset-4 hover:no-underline dark:text-indigo-300 ${FOCUS}`}
              >
                {open ? "Hide" : "Show"} {config?.tools ?? "the tools for this step"}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Under the whole row, not beside the checkbox: the tools hold tables and need the width. */}
      {hasTools && open && (
        <div
          id={toolsId}
          className="bg-background mt-4 rounded-lg border border-zinc-200 p-3 sm:p-4 dark:border-zinc-800"
        >
          {tools}
        </div>
      )}
    </li>
  );
}
