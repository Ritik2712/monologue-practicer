"use client";

import { useEffect, useSyncExternalStore } from "react";

import { PRACTICE_ROUTINE } from "./config";
import { createPracticeStore, type PracticeAction, type PracticeSnapshot } from "./practiceStore";
import { getLocalStorage, PRACTICE_STORAGE_KEY } from "./storage";

/** How often the countdown is redrawn while running. The end timestamp, not this, keeps time. */
const RUNNING_TICK_MS = 250;
/** While nothing is running, the clock is only checked to notice a new day. */
const IDLE_TICK_MS = 15_000;

// One store for the whole page, so remounting a component can never create a second timer.
const practiceStore = createPracticeStore({
  getStorage: getLocalStorage,
  now: Date.now,
  steps: PRACTICE_ROUTINE.steps,
});

// The server has no access to this browser's saved data, so it renders a loading state.
const getServerSnapshot = () => null;

export function usePracticeChecklist(): {
  snapshot: PracticeSnapshot | null;
  dispatch: (action: PracticeAction) => void;
} {
  const snapshot = useSyncExternalStore<PracticeSnapshot | null>(
    practiceStore.subscribe,
    practiceStore.getSnapshot,
    getServerSnapshot,
  );
  const running = snapshot?.record.timer.status === "running";

  useEffect(() => {
    practiceStore.tick();
    const interval = window.setInterval(
      practiceStore.tick,
      running ? RUNNING_TICK_MS : IDLE_TICK_MS,
    );
    return () => window.clearInterval(interval);
  }, [running]);

  useEffect(() => {
    // Browsers slow down or stop timers in background tabs, so catch up on return.
    const catchUp = () => {
      if (document.visibilityState === "visible") practiceStore.tick();
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === PRACTICE_STORAGE_KEY || event.key === null) practiceStore.reload();
    };
    document.addEventListener("visibilitychange", catchUp);
    window.addEventListener("focus", catchUp);
    window.addEventListener("pageshow", catchUp);
    window.addEventListener("storage", onStorage);
    return () => {
      document.removeEventListener("visibilitychange", catchUp);
      window.removeEventListener("focus", catchUp);
      window.removeEventListener("pageshow", catchUp);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  return { snapshot, dispatch: practiceStore.dispatch };
}
