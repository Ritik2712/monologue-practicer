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

/** The monologue a round is practised on. The title is kept so history still reads after it is deleted. */
export type PracticeMonologue = { id: string; title: string };

/** A round of the routine that was finished earlier the same day. */
export type PracticeRound = {
  /** Null for a round done before a monologue was chosen on this page. */
  monologue: PracticeMonologue | null;
  completed: number;
  skipped: number;
  total: number;
  finishedAtEpochMs: number;
};

export type DailyPracticeRecord = {
  /** Local calendar date, YYYY-MM-DD. */
  localDate: string;
  /**
   * The monologue the round on screen is practised on. Null until one is chosen, and on
   * days saved before the routine was tied to a monologue.
   */
  monologue: PracticeMonologue | null;
  /** Rounds finished earlier today, oldest first. The steps below are the round after them. */
  earlierRounds: PracticeRound[];
  steps: PracticeStep[];
  /** The current step. Null when no step is left to do. Always a "not_started" step. */
  activeStepId: string | null;
  timer: TimerState;
  startedAtEpochMs: number | null;
  updatedAtEpochMs: number;
  /** Set when all steps of the round on screen are completed (skipped steps do not count). */
  routineCompletedAtEpochMs: number | null;
};

/** One day as the history shows it: every round of it, not only the one on screen. */
export type DaySummary = {
  /** Rounds with any progress, the one on screen included. */
  rounds: number;
  /** Rounds in which every step was completed. One is what makes the day's routine done. */
  fullRounds: number;
  /** The round that got furthest: the figures shown for the day. */
  best: PracticeSummary;
  /** The monologues practised, in the order they were first practised. */
  monologues: string[];
};

export type PracticeSummary = {
  total: number;
  completed: number;
  skipped: number;
  /** Completed steps as a whole-number percentage of all steps. */
  percent: number;
  routineCompleted: boolean;
};
