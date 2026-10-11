import { describe, expect, it, vi } from "vitest";

import { PRACTICE_ROUTINE } from "./config";
import { createPracticeStore } from "./practiceStore";
import { parsePracticeData, PRACTICE_STORAGE_KEY, type StorageLike } from "./storage";
import type { DailyPracticeRecord } from "./types";

const STEPS = PRACTICE_ROUTINE.steps;
const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
/** 10:00 local time on 10 Oct 2026. */
const T0 = new Date(2026, 9, 10, 10, 0, 0).getTime();

function createFakeStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  const storage: StorageLike = {
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => void map.set(key, value),
    removeItem: (key) => void map.delete(key),
  };
  return { storage, map };
}

function createClock(startMs: number) {
  let nowMs = startMs;
  return {
    now: () => nowMs,
    advance: (ms: number) => void (nowMs += ms),
    set: (ms: number) => void (nowMs = ms),
  };
}

/** A new store over the same storage behaves like the page after a refresh. */
function openPage(fake = createFakeStorage(), clock = createClock(T0)) {
  const store = createPracticeStore({
    getStorage: () => fake.storage,
    now: clock.now,
    steps: STEPS,
  });
  store.tick();
  return { store, clock, fake };
}

const savedDays = (fake: ReturnType<typeof createFakeStorage>) =>
  parsePracticeData(fake.map.get(PRACTICE_STORAGE_KEY) ?? null).data.days;
const completedIds = (record: DailyPracticeRecord) =>
  record.steps.filter((step) => step.status === "completed").map((step) => step.id);

describe("saving", () => {
  it("does not save a day with no progress", () => {
    const { fake } = openPage();
    expect(fake.map.has(PRACTICE_STORAGE_KEY)).toBe(false);
  });

  it("saves progress under the local date and only under its own key", () => {
    const fake = createFakeStorage({ "some-other-app-data": "keep me" });
    const { store } = openPage(fake);
    store.dispatch({ type: "set_completed", stepId: "listen", completed: true });

    expect(Object.keys(savedDays(fake))).toEqual(["2026-10-10"]);
    expect([...fake.map.keys()].sort()).toEqual([PRACTICE_STORAGE_KEY, "some-other-app-data"]);
  });

  it("uses the device's local date, not the UTC date", () => {
    // Tests run in Asia/Kolkata (see vitest.config.ts): 20:00 UTC is 01:30 the next day.
    const clock = createClock(Date.UTC(2026, 9, 10, 20, 0, 0));
    const { store } = openPage(createFakeStorage(), clock);
    expect(store.getSnapshot().todayKey).toBe("2026-10-11");
    expect(store.getSnapshot().record.localDate).toBe("2026-10-11");
  });
});

describe("restoring after a refresh", () => {
  it("continues a running timer from its end timestamp instead of restarting it", () => {
    const first = openPage();
    first.store.dispatch({ type: "start" });
    first.clock.advance(MINUTE);

    const second = openPage(first.fake, first.clock);
    const { record, remainingMs } = second.store.getSnapshot();
    expect(record.timer).toEqual({ status: "running", endsAtEpochMs: T0 + 3 * MINUTE });
    expect(remainingMs).toBe(2 * MINUTE);
  });

  it("completes the step once if the timer ended while the page was closed", () => {
    const first = openPage();
    first.store.dispatch({ type: "start" });
    first.clock.advance(HOUR);

    const second = openPage(first.fake, first.clock);
    const { record, remainingMs } = second.store.getSnapshot();
    expect(completedIds(record)).toEqual(["listen"]);
    expect(record.activeStepId).toBe("mark");
    expect(record.timer).toEqual({ status: "idle" });
    expect(remainingMs).toBe(3 * MINUTE);
    expect(completedIds(savedDays(first.fake)["2026-10-10"])).toEqual(["listen"]);
  });

  it("keeps a paused timer paused with the same remaining time", () => {
    const first = openPage();
    first.store.dispatch({ type: "start" });
    first.clock.advance(MINUTE);
    first.store.dispatch({ type: "pause" });
    first.clock.advance(HOUR);

    const { record, remainingMs } = openPage(first.fake, first.clock).store.getSnapshot();
    expect(record.timer).toEqual({ status: "paused", remainingMs: 2 * MINUTE });
    expect(remainingMs).toBe(2 * MINUTE);
  });

  it("restores completed, skipped and not-started steps distinctly", () => {
    const first = openPage();
    first.store.dispatch({ type: "set_completed", stepId: "listen", completed: true });
    first.store.dispatch({ type: "skip_step" });

    const { record } = openPage(first.fake, first.clock).store.getSnapshot();
    expect(record.steps.map((step) => step.status)).toEqual([
      "completed",
      "skipped",
      "not_started",
      "not_started",
      "not_started",
    ]);
    expect(record.activeStepId).toBe("perform");
  });
});

describe("ticking", () => {
  it("completes an expired step exactly once, even after a long gap with no ticks", () => {
    const { store, clock } = openPage();
    store.dispatch({ type: "start" });

    // A background tab: no ticks at all for 20 minutes.
    clock.advance(20 * MINUTE);
    store.tick();
    store.tick();
    store.tick();

    const { record } = store.getSnapshot();
    expect(completedIds(record)).toEqual(["listen"]);
    expect(record.timer).toEqual({ status: "idle" });
  });

  it("notifies only when something visible changed", () => {
    const { store, clock } = openPage();
    const listener = vi.fn();
    store.subscribe(listener);

    const idle = store.getSnapshot();
    clock.advance(5 * SECOND);
    store.tick();
    expect(store.getSnapshot()).toBe(idle);
    expect(listener).not.toHaveBeenCalled();

    store.dispatch({ type: "start" });
    listener.mockClear();
    clock.advance(100);
    store.tick();
    clock.advance(100);
    store.tick();
    expect(listener).not.toHaveBeenCalled(); // 179.8 s left still shows as 03:00
    clock.advance(SECOND);
    store.tick();
    expect(listener).toHaveBeenCalledTimes(1); // now 02:59
  });

  it("stops notifying a listener after it unsubscribes", () => {
    const { store } = openPage();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    unsubscribe();
    store.dispatch({ type: "start" });
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("a new day", () => {
  it("starts a fresh checklist and keeps the previous day as history", () => {
    const { store, clock, fake } = openPage();
    store.dispatch({ type: "set_completed", stepId: "listen", completed: true });
    store.dispatch({ type: "set_completed", stepId: "mark", completed: true });

    clock.advance(DAY);
    store.tick();

    const { record, history, todayKey } = store.getSnapshot();
    expect(todayKey).toBe("2026-10-11");
    expect(record.localDate).toBe("2026-10-11");
    expect(completedIds(record)).toEqual([]);
    expect(history.map((day) => day.localDate)).toEqual(["2026-10-10"]);
    expect(completedIds(history[0])).toEqual(["listen", "mark"]);
    expect(Object.keys(savedDays(fake))).toEqual(["2026-10-10"]);

    store.dispatch({ type: "set_completed", stepId: "listen", completed: true });
    expect(Object.keys(savedDays(fake)).sort()).toEqual(["2026-10-10", "2026-10-11"]);
    expect(completedIds(savedDays(fake)["2026-10-10"])).toEqual(["listen", "mark"]);
  });

  it("is also picked up when the page is opened the next day", () => {
    const first = openPage();
    first.store.dispatch({ type: "skip_step" });
    first.clock.advance(DAY);

    const { record, history } = openPage(first.fake, first.clock).store.getSnapshot();
    expect(record.localDate).toBe("2026-10-11");
    expect(history.map((day) => day.localDate)).toEqual(["2026-10-10"]);
  });

  it("lets a timer that is running at midnight finish for the day it started", () => {
    const clock = createClock(new Date(2026, 9, 10, 23, 59, 0).getTime());
    const { store } = openPage(createFakeStorage(), clock);
    store.dispatch({ type: "start" });

    clock.advance(2 * MINUTE); // 00:01, one minute left
    store.tick();
    expect(store.getSnapshot().todayKey).toBe("2026-10-11");
    expect(store.getSnapshot().record.localDate).toBe("2026-10-10");
    expect(store.getSnapshot().record.timer.status).toBe("running");

    clock.advance(2 * MINUTE); // 00:03, expired
    store.tick();
    const { record, history } = store.getSnapshot();
    expect(record.localDate).toBe("2026-10-11");
    expect(completedIds(record)).toEqual([]);
    expect(completedIds(history[0])).toEqual(["listen"]);
  });

  it("drops a paused timer from the old day without completing its step", () => {
    const first = openPage();
    first.store.dispatch({ type: "set_completed", stepId: "listen", completed: true });
    first.store.dispatch({ type: "start" });
    first.store.dispatch({ type: "pause" });
    first.clock.advance(DAY);

    const { record, history } = openPage(first.fake, first.clock).store.getSnapshot();
    expect(record.timer).toEqual({ status: "idle" });
    expect(history[0].timer).toEqual({ status: "idle" });
    expect(completedIds(history[0])).toEqual(["listen"]);
  });

  it("keeps only the newest days when there are more than the limit", () => {
    const fake = createFakeStorage();
    const clock = createClock(T0);
    const store = createPracticeStore({
      getStorage: () => fake.storage,
      now: clock.now,
      steps: STEPS,
      maxDays: 3,
    });
    for (let day = 0; day < 5; day++) {
      store.dispatch({ type: "set_completed", stepId: "listen", completed: true });
      clock.advance(DAY);
    }
    store.tick();
    expect(Object.keys(savedDays(fake)).sort()).toEqual([
      "2026-10-12",
      "2026-10-13",
      "2026-10-14",
    ]);
  });
});

describe("resetting and clearing", () => {
  function twoDays() {
    const page = openPage();
    page.store.dispatch({ type: "set_completed", stepId: "listen", completed: true });
    page.clock.advance(DAY);
    page.store.tick();
    page.store.dispatch({ type: "set_completed", stepId: "mark", completed: true });
    page.store.dispatch({ type: "start" });
    return page;
  }

  it("reset today clears only today's checklist", () => {
    const { store, fake } = twoDays();
    store.dispatch({ type: "reset_today" });

    const { record, history } = store.getSnapshot();
    expect(completedIds(record)).toEqual([]);
    expect(record.timer).toEqual({ status: "idle" });
    expect(record.activeStepId).toBe("listen");
    expect(history.map((day) => day.localDate)).toEqual(["2026-10-10"]);
    expect(Object.keys(savedDays(fake))).toEqual(["2026-10-10"]);
  });

  it("removes its storage key entirely once nothing is left to keep", () => {
    const { store, fake } = openPage();
    store.dispatch({ type: "skip_step" });
    expect(fake.map.has(PRACTICE_STORAGE_KEY)).toBe(true);

    store.dispatch({ type: "reset_today" });
    expect(fake.map.has(PRACTICE_STORAGE_KEY)).toBe(false);
  });

  it("clear history removes previous days and keeps today's progress and other keys", () => {
    const { store, fake } = twoDays();
    fake.map.set("unrelated", "value");
    store.dispatch({ type: "clear_history" });

    const { record, history } = store.getSnapshot();
    expect(history).toEqual([]);
    expect(completedIds(record)).toEqual(["mark"]);
    expect(record.timer.status).toBe("running");
    expect(Object.keys(savedDays(fake))).toEqual(["2026-10-11"]);
    expect(fake.map.get("unrelated")).toBe("value");
  });
});

describe("damaged or unavailable storage", () => {
  it("falls back to a fresh checklist when saved data is not valid JSON", () => {
    const fake = createFakeStorage({ [PRACTICE_STORAGE_KEY]: "{not json" });
    const { store } = openPage(fake);

    const { record, warning } = store.getSnapshot();
    expect(warning).toBe("corrupt");
    expect(completedIds(record)).toEqual([]);
    // Unreadable data is not wiped just by opening the page...
    expect(fake.map.get(PRACTICE_STORAGE_KEY)).toBe("{not json");

    // ...only replaced once there is real progress to save.
    store.dispatch({ type: "set_completed", stepId: "listen", completed: true });
    expect(Object.keys(savedDays(fake))).toEqual(["2026-10-10"]);
  });

  it("keeps valid days and drops invalid ones", () => {
    const seed = openPage();
    seed.store.dispatch({ type: "set_completed", stepId: "listen", completed: true });
    const data = JSON.parse(seed.fake.map.get(PRACTICE_STORAGE_KEY) as string);
    data.days["2026-10-09"] = { localDate: "2026-10-09", steps: "nonsense" };
    data.days["not-a-date"] = data.days["2026-10-10"];
    const fake = createFakeStorage({ [PRACTICE_STORAGE_KEY]: JSON.stringify(data) });

    const { record, history, warning } = openPage(fake, seed.clock).store.getSnapshot();
    expect(warning).toBe("partially_invalid");
    expect(completedIds(record)).toEqual(["listen"]);
    expect(history).toEqual([]);
  });

  it("repairs a saved timer that points at a finished step", () => {
    const seed = openPage();
    seed.store.dispatch({ type: "start" });
    const data = JSON.parse(seed.fake.map.get(PRACTICE_STORAGE_KEY) as string);
    data.days["2026-10-10"].steps[0].status = "completed";
    const fake = createFakeStorage({ [PRACTICE_STORAGE_KEY]: JSON.stringify(data) });
    seed.clock.advance(HOUR);

    const { record } = openPage(fake, seed.clock).store.getSnapshot();
    expect(completedIds(record)).toEqual(["listen"]);
    expect(record.activeStepId).toBe("mark");
    expect(record.timer).toEqual({ status: "idle" });
  });

  it("still works in memory when storage is unavailable", () => {
    const clock = createClock(T0);
    const store = createPracticeStore({ getStorage: () => null, now: clock.now, steps: STEPS });
    store.dispatch({ type: "start" });
    clock.advance(3 * MINUTE);
    store.tick();

    expect(store.getSnapshot().warning).toBe("unavailable");
    expect(completedIds(store.getSnapshot().record)).toEqual(["listen"]);
  });

  it("reports a failed save and keeps the on-screen state", () => {
    const fake = createFakeStorage();
    fake.storage.setItem = () => {
      throw new Error("QuotaExceededError");
    };
    const { store } = openPage(fake);
    store.dispatch({ type: "set_completed", stepId: "listen", completed: true });

    expect(store.getSnapshot().warning).toBe("write_failed");
    expect(completedIds(store.getSnapshot().record)).toEqual(["listen"]);

    store.dispatch({ type: "dismiss_warning" });
    expect(store.getSnapshot().warning).toBeNull();
  });
});

describe("another tab", () => {
  it("picks up changes saved by another tab on reload", () => {
    const tabA = openPage();
    const tabB = openPage(tabA.fake, tabA.clock);
    const listener = vi.fn();
    tabB.store.subscribe(listener);

    tabA.store.dispatch({ type: "set_completed", stepId: "listen", completed: true });
    tabA.store.dispatch({ type: "start" });
    tabB.store.reload();

    const { record } = tabB.store.getSnapshot();
    expect(completedIds(record)).toEqual(["listen"]);
    expect(record.timer).toEqual(tabA.store.getSnapshot().record.timer);
    expect(listener).toHaveBeenCalled();
  });
});
