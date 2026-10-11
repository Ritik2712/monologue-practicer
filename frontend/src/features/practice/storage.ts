/**
 * Reading and writing the checklist's saved data. Everything loaded from the browser is
 * treated as untrusted: it may be hand-edited, cut off, or written by an older version.
 */
import { isLocalDateKey } from "./localDate";
import { nextUnfinishedStepId } from "./practiceState";
import type { DailyPracticeRecord, PracticeStep, StepStatus, TimerState } from "./types";

/** The only browser-storage key this feature touches. */
export const PRACTICE_STORAGE_KEY = "monologue-coach.practice.v1";

export type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export type PracticeData = {
  schemaVersion: 1;
  /** One record per local calendar day that has any progress, keyed by YYYY-MM-DD. */
  days: Record<string, DailyPracticeRecord>;
};

/** "corrupt": nothing could be read. "partially_invalid": some days were dropped. */
export type LoadProblem = "none" | "corrupt" | "partially_invalid";

export type LoadResult = { data: PracticeData; problem: LoadProblem };

const STEP_STATUSES: readonly StepStatus[] = ["not_started", "completed", "skipped"];

export function serializePracticeData(days: Record<string, DailyPracticeRecord>): string {
  const data: PracticeData = { schemaVersion: 1, days };
  return JSON.stringify(data);
}

export function parsePracticeData(raw: string | null): LoadResult {
  const empty: PracticeData = { schemaVersion: 1, days: {} };
  if (raw === null) return { data: empty, problem: "none" };

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { data: empty, problem: "corrupt" };
  }
  if (!isObject(parsed) || parsed.schemaVersion !== 1 || !isObject(parsed.days)) {
    return { data: empty, problem: "corrupt" };
  }

  const days: Record<string, DailyPracticeRecord> = {};
  let dropped = false;
  for (const [key, value] of Object.entries(parsed.days)) {
    const record = parseRecord(key, value);
    if (record) days[key] = record;
    else dropped = true;
  }
  return { data: { schemaVersion: 1, days }, problem: dropped ? "partially_invalid" : "none" };
}

/** Local storage if it is usable, otherwise null (private mode, blocked by settings, etc.). */
export function getLocalStorage(): StorageLike | null {
  try {
    const storage = window.localStorage;
    const probe = `${PRACTICE_STORAGE_KEY}.probe`;
    storage.setItem(probe, "1");
    storage.removeItem(probe);
    return storage;
  } catch {
    return null;
  }
}

function parseRecord(key: string, value: unknown): DailyPracticeRecord | null {
  if (!isObject(value) || !isLocalDateKey(key) || value.localDate !== key) return null;
  if (!Array.isArray(value.steps) || value.steps.length === 0) return null;

  const steps: PracticeStep[] = [];
  for (const raw of value.steps) {
    const step = parseStep(raw);
    if (!step || steps.some((existing) => existing.id === step.id)) return null;
    steps.push(step);
  }

  const timer = parseTimer(value.timer);
  if (!timer || !isFiniteNumber(value.updatedAtEpochMs)) return null;
  if (!isNullableNumber(value.startedAtEpochMs)) return null;
  if (!isNullableNumber(value.routineCompletedAtEpochMs)) return null;
  if (value.activeStepId !== null && typeof value.activeStepId !== "string") return null;

  // Repair rather than reject a record whose parts disagree with each other: the active
  // step must be an unfinished one, and only an active step can have a live timer.
  const savedActive = steps.find((step) => step.id === value.activeStepId);
  const activeIsValid = savedActive?.status === "not_started";
  const allCompleted = steps.every((step) => step.status === "completed");
  return {
    localDate: key,
    steps,
    activeStepId: activeIsValid ? savedActive.id : nextUnfinishedStepId(steps, null),
    timer: activeIsValid ? timer : { status: "idle" },
    startedAtEpochMs: value.startedAtEpochMs,
    updatedAtEpochMs: value.updatedAtEpochMs,
    routineCompletedAtEpochMs: allCompleted
      ? (value.routineCompletedAtEpochMs ?? value.updatedAtEpochMs)
      : null,
  };
}

function parseStep(value: unknown): PracticeStep | null {
  if (!isObject(value)) return null;
  const { id, title, durationSeconds, status } = value;
  if (typeof id !== "string" || id === "" || typeof title !== "string") return null;
  if (!isFiniteNumber(durationSeconds) || durationSeconds <= 0) return null;
  if (!STEP_STATUSES.includes(status as StepStatus)) return null;
  return { id, title, durationSeconds, status: status as StepStatus };
}

function parseTimer(value: unknown): TimerState | null {
  if (!isObject(value)) return null;
  switch (value.status) {
    case "idle":
      return { status: "idle" };
    case "running":
      return isFiniteNumber(value.endsAtEpochMs)
        ? { status: "running", endsAtEpochMs: value.endsAtEpochMs }
        : null;
    case "paused":
      return isFiniteNumber(value.remainingMs) && value.remainingMs > 0
        ? { status: "paused", remainingMs: value.remainingMs }
        : null;
    default:
      return null;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value);
}
