export type StepStatus = "not_started" | "completed" | "skipped";

export type PracticeStep = {
  id: string;
  /** Copied from the config when the day starts, so history still reads correctly if the config changes. */
  title: string;
  durationSeconds: number;
  status: StepStatus;
};

/**
 * The single countdown, which always belongs to the active step.
 * While running, `endsAtEpochMs` is the source of truth: remaining time is derived from it,
 * never counted down tick by tick.
 */
export type TimerState =
  | { status: "idle" }
  | { status: "running"; endsAtEpochMs: number }
  | { status: "paused"; remainingMs: number };

export type DailyPracticeRecord = {
  /** Local calendar date, YYYY-MM-DD. */
  localDate: string;
  steps: PracticeStep[];
  /** The current step. Null when no step is left to do. Always a "not_started" step. */
  activeStepId: string | null;
  timer: TimerState;
  startedAtEpochMs: number | null;
  updatedAtEpochMs: number;
  /** Set when all steps are completed (skipped steps do not count). */
  routineCompletedAtEpochMs: number | null;
};

export type PracticeSummary = {
  total: number;
  completed: number;
  skipped: number;
  /** Completed steps as a whole-number percentage of all steps. */
  percent: number;
  routineCompleted: boolean;
};
