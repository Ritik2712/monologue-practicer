/**
 * Pure checklist and timer rules. No React, no storage, no clock: every function takes the
 * current record plus "now" and returns the next record. A function that has nothing to do
 * returns the same object, so callers can detect changes with `===`.
 */
import type { PracticeStepConfig } from "./config";
import type {
  DailyPracticeRecord,
  DaySummary,
  PracticeMonologue,
  PracticeRound,
  PracticeStep,
  PracticeSummary,
} from "./types";

function freshSteps(steps: readonly PracticeStepConfig[]): PracticeStep[] {
  return steps.map(({ id, title, durationSeconds }) => ({
    id,
    title,
    durationSeconds,
    status: "not_started",
  }));
}

export function createDailyRecord(
  localDate: string,
  steps: readonly PracticeStepConfig[],
  nowMs: number,
  monologue: PracticeMonologue | null = null,
): DailyPracticeRecord {
  return {
    localDate,
    monologue,
    earlierRounds: [],
    steps: freshSteps(steps),
    activeStepId: steps[0]?.id ?? null,
    timer: { status: "idle" },
    startedAtEpochMs: null,
    updatedAtEpochMs: nowMs,
    routineCompletedAtEpochMs: null,
  };
}

export function getActiveStep(record: DailyPracticeRecord): PracticeStep | null {
  return record.steps.find((step) => step.id === record.activeStepId) ?? null;
}

/** Time left on the active step. Derived from the end timestamp while the timer is running. */
export function remainingMs(record: DailyPracticeRecord, nowMs: number): number {
  const active = getActiveStep(record);
  if (!active) return 0;
  const fullMs = active.durationSeconds * 1000;
  switch (record.timer.status) {
    case "idle":
      return fullMs;
    case "paused":
      return clamp(record.timer.remainingMs, 0, fullMs);
    case "running":
      return clamp(record.timer.endsAtEpochMs - nowMs, 0, fullMs);
  }
}

/** First "not_started" step after `afterStepId`, wrapping round to the start of the list. */
export function nextUnfinishedStepId(
  steps: readonly PracticeStep[],
  afterStepId: string | null,
): string | null {
  const start = steps.findIndex((step) => step.id === afterStepId);
  for (let offset = 1; offset <= steps.length; offset++) {
    const step = steps[(start + offset) % steps.length];
    if (step.status === "not_started") return step.id;
  }
  return null;
}

/**
 * Settles a timer whose end time has passed: the active step becomes completed, exactly once.
 * Every action below runs this first, so a stale timer can never complete the wrong step.
 */
export function reconcile(record: DailyPracticeRecord, nowMs: number): DailyPracticeRecord {
  if (record.timer.status !== "running") return record;
  const active = getActiveStep(record);
  if (!active) return { ...record, timer: { status: "idle" } };
  if (nowMs < record.timer.endsAtEpochMs) return record;
  return completeStep(record, active.id, record.timer.endsAtEpochMs);
}

export function startTimer(record: DailyPracticeRecord, nowMs: number): DailyPracticeRecord {
  const current = reconcile(record, nowMs);
  const active = getActiveStep(current);
  if (!active || current.timer.status !== "idle") return current;
  return {
    ...current,
    timer: { status: "running", endsAtEpochMs: nowMs + active.durationSeconds * 1000 },
    startedAtEpochMs: current.startedAtEpochMs ?? nowMs,
    updatedAtEpochMs: nowMs,
  };
}

export function pauseTimer(record: DailyPracticeRecord, nowMs: number): DailyPracticeRecord {
  const current = reconcile(record, nowMs);
  if (current.timer.status !== "running") return current;
  return {
    ...current,
    timer: { status: "paused", remainingMs: current.timer.endsAtEpochMs - nowMs },
    updatedAtEpochMs: nowMs,
  };
}

export function resumeTimer(record: DailyPracticeRecord, nowMs: number): DailyPracticeRecord {
  if (record.timer.status !== "paused") return reconcile(record, nowMs);
  return {
    ...record,
    timer: { status: "running", endsAtEpochMs: nowMs + record.timer.remainingMs },
    updatedAtEpochMs: nowMs,
  };
}

/** Stops the timer and puts the active step back to its full duration. */
export function resetStep(record: DailyPracticeRecord, nowMs: number): DailyPracticeRecord {
  const current = reconcile(record, nowMs);
  if (current.timer.status === "idle") return current;
  return { ...current, timer: { status: "idle" }, updatedAtEpochMs: nowMs };
}

/** Marks the active step skipped (not completed) and moves on to the next unfinished step. */
export function skipStep(record: DailyPracticeRecord, nowMs: number): DailyPracticeRecord {
  const current = reconcile(record, nowMs);
  const active = getActiveStep(current);
  if (!active) return current;
  const steps = current.steps.map((step) =>
    step.id === active.id ? { ...step, status: "skipped" as const } : step,
  );
  return {
    ...current,
    steps,
    activeStepId: nextUnfinishedStepId(steps, active.id),
    timer: { status: "idle" },
    updatedAtEpochMs: nowMs,
  };
}

/** Manual check or uncheck of any step. Checking the active step stops its timer. */
export function setStepCompleted(
  record: DailyPracticeRecord,
  stepId: string,
  completed: boolean,
  nowMs: number,
): DailyPracticeRecord {
  const current = reconcile(record, nowMs);
  const step = current.steps.find((candidate) => candidate.id === stepId);
  if (!step) return current;

  if (completed) {
    return step.status === "completed" ? current : completeStep(current, stepId, nowMs);
  }
  if (step.status !== "completed") return current;
  return {
    ...current,
    steps: current.steps.map((candidate) =>
      candidate.id === stepId ? { ...candidate, status: "not_started" as const } : candidate,
    ),
    activeStepId: current.activeStepId ?? stepId,
    updatedAtEpochMs: nowMs,
    routineCompletedAtEpochMs: null,
  };
}

/**
 * Makes another unfinished step the current one. The timer belongs to the step being left,
 * so it is stopped. Selecting a skipped step un-skips it.
 */
export function selectStep(
  record: DailyPracticeRecord,
  stepId: string,
  nowMs: number,
): DailyPracticeRecord {
  const current = reconcile(record, nowMs);
  const step = current.steps.find((candidate) => candidate.id === stepId);
  if (!step || step.status === "completed" || current.activeStepId === stepId) return current;
  return {
    ...current,
    steps: current.steps.map((candidate) =>
      candidate.id === stepId ? { ...candidate, status: "not_started" as const } : candidate,
    ),
    activeStepId: stepId,
    timer: { status: "idle" },
    updatedAtEpochMs: nowMs,
  };
}

/** Used when a day is filed away as history: a past day never keeps a live timer. */
export function closeOut(record: DailyPracticeRecord): DailyPracticeRecord {
  return record.timer.status === "idle" ? record : { ...record, timer: { status: "idle" } };
}

/** True while nothing has been done in the round on screen. */
export function isRoundUntouched(record: DailyPracticeRecord): boolean {
  return (
    record.timer.status === "idle" &&
    record.activeStepId === (record.steps[0]?.id ?? null) &&
    record.steps.every((step) => step.status === "not_started")
  );
}

/**
 * True when the record is indistinguishable from a brand-new day, so it need not be saved.
 * Choosing a monologue is not progress: a day on which nothing was practised leaves no trace.
 */
export function isPristine(record: DailyPracticeRecord): boolean {
  return record.earlierRounds.length === 0 && isRoundUntouched(record);
}

/** True when the round on screen has no step left to do: each is completed or skipped. */
export function isRoundFinished(record: DailyPracticeRecord): boolean {
  return (
    record.steps.length > 0 &&
    record.timer.status === "idle" &&
    record.steps.every((step) => step.status !== "not_started")
  );
}

/**
 * Says which monologue the round on screen is practised on.
 *
 * A round that has been started stays on its monologue: asking for another one then changes
 * nothing, and the caller offers `switchMonologue` or a new round instead. The title of the
 * same monologue is brought up to date, in case it was not known or has changed.
 */
export function setMonologue(
  record: DailyPracticeRecord,
  monologue: PracticeMonologue,
  nowMs: number,
): DailyPracticeRecord {
  const current = reconcile(record, nowMs);
  const chosen = current.monologue;
  if (chosen?.id === monologue.id && chosen.title === monologue.title) return current;
  const free = chosen === null || chosen.id === monologue.id || isRoundUntouched(current);
  return free ? { ...current, monologue } : current;
}

/** Abandons the round on screen and starts it afresh on another monologue. Earlier rounds stay. */
export function switchMonologue(
  record: DailyPracticeRecord,
  monologue: PracticeMonologue,
  config: readonly PracticeStepConfig[],
  nowMs: number,
): DailyPracticeRecord {
  return {
    ...record,
    monologue,
    steps: freshSteps(config),
    activeStepId: config[0]?.id ?? null,
    timer: { status: "idle" },
    updatedAtEpochMs: nowMs,
    routineCompletedAtEpochMs: null,
  };
}

/**
 * Files the finished round on screen under "earlier today" and starts another, on the same
 * monologue or a different one. Does nothing while the round still has a step to do.
 */
export function startNextRound(
  record: DailyPracticeRecord,
  monologue: PracticeMonologue | null,
  config: readonly PracticeStepConfig[],
  nowMs: number,
): DailyPracticeRecord {
  const current = reconcile(record, nowMs);
  if (!isRoundFinished(current)) return current;
  const { completed, skipped, total } = summarize(current);
  const finished: PracticeRound = {
    monologue: current.monologue,
    completed,
    skipped,
    total,
    finishedAtEpochMs: current.updatedAtEpochMs,
  };
  return {
    ...current,
    monologue,
    earlierRounds: [...current.earlierRounds, finished],
    steps: freshSteps(config),
    activeStepId: config[0]?.id ?? null,
    timer: { status: "idle" },
    updatedAtEpochMs: nowMs,
    routineCompletedAtEpochMs: null,
  };
}

export function summarize(record: DailyPracticeRecord): PracticeSummary {
  const total = record.steps.length;
  const completed = record.steps.filter((step) => step.status === "completed").length;
  const skipped = record.steps.filter((step) => step.status === "skipped").length;
  return {
    total,
    completed,
    skipped,
    percent: total === 0 ? 0 : Math.round((completed / total) * 100),
    routineCompleted: total > 0 && completed === total,
  };
}

/** A whole day: the round on screen together with the rounds finished before it. */
export function summarizeDay(record: DailyPracticeRecord): DaySummary {
  const percentOf = (completed: number, total: number) =>
    total === 0 ? 0 : Math.round((completed / total) * 100);
  const rounds: (PracticeSummary & { monologue: PracticeMonologue | null })[] =
    record.earlierRounds.map(({ monologue, completed, skipped, total }) => ({
      monologue,
      completed,
      skipped,
      total,
      percent: percentOf(completed, total),
      routineCompleted: total > 0 && completed === total,
    }));
  // The round on screen counts once something has been done in it.
  if (rounds.length === 0 || !isRoundUntouched(record)) {
    rounds.push({ ...summarize(record), monologue: record.monologue });
  }
  const best = rounds.reduce((top, round) => (round.completed > top.completed ? round : top));
  const monologues: string[] = [];
  for (const { monologue } of rounds) {
    if (monologue && !monologues.includes(monologue.title)) monologues.push(monologue.title);
  }
  return {
    rounds: rounds.length,
    fullRounds: rounds.filter((round) => round.routineCompleted).length,
    best: {
      total: best.total,
      completed: best.completed,
      skipped: best.skipped,
      percent: best.percent,
      routineCompleted: best.routineCompleted,
    },
    monologues,
  };
}

/**
 * Brings a saved record in line with the current config (titles, durations, added or removed
 * steps) while keeping each surviving step's status.
 */
export function syncWithConfig(
  record: DailyPracticeRecord,
  config: readonly PracticeStepConfig[],
  nowMs: number,
): DailyPracticeRecord {
  const unchanged =
    record.steps.length === config.length &&
    record.steps.every(
      (step, index) =>
        step.id === config[index].id &&
        step.title === config[index].title &&
        step.durationSeconds === config[index].durationSeconds,
    );
  if (unchanged) return record;

  const savedStatus = new Map(record.steps.map((step) => [step.id, step.status]));
  const steps: PracticeStep[] = config.map(({ id, title, durationSeconds }) => ({
    id,
    title,
    durationSeconds,
    status: savedStatus.get(id) ?? "not_started",
  }));
  const activeSurvives = steps.some(
    (step) => step.id === record.activeStepId && step.status === "not_started",
  );
  const allCompleted = steps.length > 0 && steps.every((step) => step.status === "completed");
  return {
    ...record,
    steps,
    activeStepId: activeSurvives ? record.activeStepId : nextUnfinishedStepId(steps, null),
    timer: activeSurvives ? record.timer : { status: "idle" },
    updatedAtEpochMs: nowMs,
    routineCompletedAtEpochMs: allCompleted ? (record.routineCompletedAtEpochMs ?? nowMs) : null,
  };
}

function completeStep(
  record: DailyPracticeRecord,
  stepId: string,
  atMs: number,
): DailyPracticeRecord {
  const steps = record.steps.map((step) =>
    step.id === stepId ? { ...step, status: "completed" as const } : step,
  );
  const wasActive = record.activeStepId === stepId;
  const allCompleted = steps.every((step) => step.status === "completed");
  return {
    ...record,
    steps,
    activeStepId: wasActive ? nextUnfinishedStepId(steps, stepId) : record.activeStepId,
    timer: wasActive ? { status: "idle" } : record.timer,
    updatedAtEpochMs: atMs,
    routineCompletedAtEpochMs: allCompleted ? (record.routineCompletedAtEpochMs ?? atMs) : null,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
