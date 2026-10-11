/**
 * Holds the checklist state for the page and keeps it saved. It ties together the pure rules
 * (practiceState), the saved data (storage) and the clock, and exposes the
 * subscribe/getSnapshot pair that React's useSyncExternalStore expects.
 *
 * The clock and the storage are passed in, so tests can drive time and inspect what is saved.
 */
import type { PracticeStepConfig } from "./config";
import { localDateKey } from "./localDate";
import {
  closeOut,
  createDailyRecord,
  isPristine,
  pauseTimer,
  reconcile,
  remainingMs,
  resetStep,
  resumeTimer,
  selectStep,
  setStepCompleted,
  skipStep,
  startTimer,
  syncWithConfig,
} from "./practiceState";
import {
  parsePracticeData,
  PRACTICE_STORAGE_KEY,
  serializePracticeData,
  type StorageLike,
} from "./storage";
import type { DailyPracticeRecord } from "./types";

export type StorageWarning = "unavailable" | "corrupt" | "partially_invalid" | "write_failed";

export type PracticeAction =
  | { type: "start" }
  | { type: "pause" }
  | { type: "resume" }
  | { type: "reset_step" }
  | { type: "skip_step" }
  | { type: "set_completed"; stepId: string; completed: boolean }
  | { type: "select_step"; stepId: string }
  | { type: "reset_today" }
  | { type: "clear_history" }
  | { type: "dismiss_warning" };

export type PracticeSnapshot = {
  /** The device's local date right now. */
  todayKey: string;
  /**
   * The checklist on screen. Normally today's; it is still yesterday's only while a timer
   * that was started before midnight is finishing.
   */
  record: DailyPracticeRecord;
  /** Time left on the active step. */
  remainingMs: number;
  /** Every other saved day, newest first. */
  history: DailyPracticeRecord[];
  warning: StorageWarning | null;
};

export type PracticeStore = {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => PracticeSnapshot;
  dispatch: (action: PracticeAction) => void;
  /** Re-reads the clock: settles an expired timer, rolls over to a new day, refreshes the countdown. */
  tick: () => void;
  /** Re-reads saved data after another tab changed it. */
  reload: () => void;
};

type StoreDeps = {
  getStorage: () => StorageLike | null;
  now: () => number;
  steps: readonly PracticeStepConfig[];
  /** How many days of records to keep. Older ones are dropped when saving. */
  maxDays?: number;
};

export function createPracticeStore({
  getStorage,
  now,
  steps,
  maxDays = 120,
}: StoreDeps): PracticeStore {
  const listeners = new Set<() => void>();
  let initialised = false;
  /** Saved days other than the one on screen. */
  let otherDays: Record<string, DailyPracticeRecord> = {};
  let current: DailyPracticeRecord = createDailyRecord("", steps, 0);
  let warning: StorageWarning | null = null;
  let lastWrittenJson: string | null = null;
  let loadedCorrupt = false;
  let savedCurrent: DailyPracticeRecord | null = null;
  let savedOtherDays: Record<string, DailyPracticeRecord> | null = null;
  let snapshot: PracticeSnapshot | null = null;
  /** The sorted history list is rebuilt only when `otherDays` is replaced. */
  let historySource: Record<string, DailyPracticeRecord> | null = null;
  let history: DailyPracticeRecord[] = [];

  function load(nowMs: number) {
    let raw: string | null = null;
    let readable = false;
    try {
      const storage = getStorage();
      if (storage) {
        raw = storage.getItem(PRACTICE_STORAGE_KEY);
        readable = true;
      }
    } catch {
      readable = false;
    }

    const { data, problem } = parsePracticeData(raw);
    loadedCorrupt = problem === "corrupt";
    lastWrittenJson = raw;
    if (!readable) warning = "unavailable";
    else if (problem !== "none") warning = problem;

    // A timer left running in an earlier session may have ended since: settle it first.
    const days: Record<string, DailyPracticeRecord> = {};
    for (const [key, record] of Object.entries(data.days)) days[key] = reconcile(record, nowMs);

    const todayKey = localDateKey(new Date(nowMs));
    const stillRunningKey = Object.keys(days)
      .filter((key) => days[key].timer.status === "running")
      .sort()
      .at(-1);
    const currentKey = days[todayKey] ? todayKey : stillRunningKey;

    otherDays = {};
    for (const [key, record] of Object.entries(days)) {
      if (key === currentKey) continue;
      const archived = closeOut(record);
      if (!isPristine(archived)) otherDays[key] = archived;
    }
    current = currentKey
      ? syncWithConfig(days[currentKey], steps, nowMs)
      : createDailyRecord(todayKey, steps, nowMs);
    savedCurrent = null;
    savedOtherDays = null;
  }

  /** Settles an expired timer, then moves to a fresh checklist if the local date has changed. */
  function settle(nowMs: number) {
    current = reconcile(current, nowMs);
    const todayKey = localDateKey(new Date(nowMs));
    // A timer that is still running across midnight is allowed to finish first.
    if (current.localDate === todayKey || current.timer.status === "running") return;

    const archived = closeOut(current);
    if (!isPristine(archived)) otherDays = { ...otherDays, [archived.localDate]: archived };
    const { [todayKey]: existingToday, ...rest } = otherDays;
    otherDays = existingToday ? rest : otherDays;
    current = existingToday
      ? syncWithConfig(existingToday, steps, nowMs)
      : createDailyRecord(todayKey, steps, nowMs);
  }

  function save() {
    if (current === savedCurrent && otherDays === savedOtherDays) return;
    savedCurrent = current;
    savedOtherDays = otherDays;

    const days = { ...otherDays };
    if (!isPristine(current)) days[current.localDate] = current;
    const keptKeys = Object.keys(days).sort().slice(-maxDays);
    const json = serializePracticeData(Object.fromEntries(keptKeys.map((key) => [key, days[key]])));

    const nothingToKeep = keptKeys.length === 0;
    // Unreadable saved data is left alone until there is something real to save over it.
    if (nothingToKeep && loadedCorrupt) return;
    const nextJson = nothingToKeep ? null : json;
    if (nextJson === lastWrittenJson) return;
    try {
      const storage = getStorage();
      if (!storage) return;
      // With no days left there is nothing worth keeping, so the key is removed entirely.
      if (nextJson === null) storage.removeItem(PRACTICE_STORAGE_KEY);
      else storage.setItem(PRACTICE_STORAGE_KEY, nextJson);
      lastWrittenJson = nextJson;
      loadedCorrupt = false;
    } catch {
      warning = "write_failed";
    }
  }

  function publish(nowMs: number, notify: boolean) {
    const remaining = remainingMs(current, nowMs);
    const todayKey = localDateKey(new Date(nowMs));
    const unchanged =
      snapshot !== null &&
      snapshot.record === current &&
      snapshot.todayKey === todayKey &&
      snapshot.warning === warning &&
      historySource === otherDays &&
      // The countdown only needs a re-render when the visible second changes.
      Math.ceil(snapshot.remainingMs / 1000) === Math.ceil(remaining / 1000);
    if (unchanged) return;

    if (historySource !== otherDays) {
      historySource = otherDays;
      history = Object.keys(otherDays)
        .sort()
        .reverse()
        .map((key) => otherDays[key]);
    }
    snapshot = { todayKey, record: current, remainingMs: remaining, history, warning };
    if (notify) listeners.forEach((listener) => listener());
  }

  function ensureInitialised() {
    if (initialised) return;
    initialised = true;
    const nowMs = now();
    load(nowMs);
    // No save here: this can run while React is rendering. The first tick() saves.
    publish(nowMs, false);
  }

  function apply(action: PracticeAction, nowMs: number) {
    switch (action.type) {
      case "start":
        current = startTimer(current, nowMs);
        break;
      case "pause":
        current = pauseTimer(current, nowMs);
        break;
      case "resume":
        current = resumeTimer(current, nowMs);
        break;
      case "reset_step":
        current = resetStep(current, nowMs);
        break;
      case "skip_step":
        current = skipStep(current, nowMs);
        break;
      case "set_completed":
        current = setStepCompleted(current, action.stepId, action.completed, nowMs);
        break;
      case "select_step":
        current = selectStep(current, action.stepId, nowMs);
        break;
      case "reset_today":
        // Only the checklist on screen is replaced; other days are untouched.
        current = createDailyRecord(current.localDate, steps, nowMs);
        break;
      case "clear_history":
        if (Object.keys(otherDays).length > 0) otherDays = {};
        break;
      case "dismiss_warning":
        warning = null;
        break;
    }
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot() {
      ensureInitialised();
      return snapshot as PracticeSnapshot;
    },
    dispatch(action) {
      ensureInitialised();
      const nowMs = now();
      settle(nowMs);
      apply(action, nowMs);
      settle(nowMs);
      save();
      publish(nowMs, true);
    },
    tick() {
      ensureInitialised();
      const nowMs = now();
      settle(nowMs);
      save();
      publish(nowMs, true);
    },
    reload() {
      initialised = true;
      const nowMs = now();
      load(nowMs);
      settle(nowMs);
      save();
      publish(nowMs, true);
    },
  };
}
