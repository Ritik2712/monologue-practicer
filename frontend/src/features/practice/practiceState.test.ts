import { describe, expect, it } from "vitest";

import { PRACTICE_ROUTINE } from "./config";
import {
  createDailyRecord,
  isPristine,
  isRoundFinished,
  isRoundUntouched,
  pauseTimer,
  reconcile,
  remainingMs,
  resetStep,
  resumeTimer,
  selectStep,
  setMonologue,
  setStepCompleted,
  skipStep,
  startNextRound,
  startTimer,
  summarize,
  summarizeDay,
  switchMonologue,
  syncWithConfig,
} from "./practiceState";
import type { DailyPracticeRecord } from "./types";

const STEPS = PRACTICE_ROUTINE.steps;
const T0 = new Date(2026, 9, 10, 10, 0, 0).getTime();
const SECOND = 1000;
const MINUTE = 60 * SECOND;

const fresh = () => createDailyRecord("2026-10-10", STEPS, T0);
const statuses = (record: DailyPracticeRecord) => record.steps.map((step) => step.status);

describe("default routine", () => {
  it("is five steps totalling 15 minutes with the first step current", () => {
    const record = fresh();
    expect(record.steps.map((step) => step.durationSeconds)).toEqual([180, 180, 240, 180, 120]);
    expect(record.steps.reduce((sum, step) => sum + step.durationSeconds, 0)).toBe(15 * 60);
    expect(record.activeStepId).toBe("listen");
    expect(isPristine(record)).toBe(true);
  });
});

describe("countdown", () => {
  it("starts at the active step's full duration and stores an end timestamp", () => {
    const running = startTimer(fresh(), T0);
    expect(running.timer).toEqual({ status: "running", endsAtEpochMs: T0 + 3 * MINUTE });
    expect(running.startedAtEpochMs).toBe(T0);
    expect(remainingMs(running, T0)).toBe(3 * MINUTE);
  });

  it("derives remaining time from the end timestamp, however irregular the checks are", () => {
    const running = startTimer(fresh(), T0);
    expect(remainingMs(running, T0 + 1300)).toBe(3 * MINUTE - 1300);
    expect(remainingMs(running, T0 + 95 * SECOND)).toBe(85 * SECOND);
    expect(remainingMs(running, T0 + 10 * MINUTE)).toBe(0);
  });

  it("ignores a second start while already running", () => {
    const running = startTimer(fresh(), T0);
    expect(startTimer(running, T0 + SECOND)).toBe(running);
  });

  it("freezes on pause and continues from the same remaining time on resume", () => {
    const paused = pauseTimer(startTimer(fresh(), T0), T0 + MINUTE);
    expect(paused.timer).toEqual({ status: "paused", remainingMs: 2 * MINUTE });
    expect(remainingMs(paused, T0 + 30 * MINUTE)).toBe(2 * MINUTE);

    const resumed = resumeTimer(paused, T0 + 30 * MINUTE);
    expect(resumed.timer).toEqual({ status: "running", endsAtEpochMs: T0 + 32 * MINUTE });
    expect(statuses(reconcile(resumed, T0 + 31 * MINUTE))[0]).toBe("not_started");
  });

  it("reset step stops the timer and restores the full duration without changing status", () => {
    const reset = resetStep(startTimer(fresh(), T0), T0 + MINUTE);
    expect(reset.timer).toEqual({ status: "idle" });
    expect(remainingMs(reset, T0 + MINUTE)).toBe(3 * MINUTE);
    expect(statuses(reset)[0]).toBe("not_started");
    expect(resetStep(reset, T0 + 2 * MINUTE)).toBe(reset);
  });
});

describe("expiry", () => {
  it("completes the active step and moves to the next one without starting it", () => {
    const expired = reconcile(startTimer(fresh(), T0), T0 + 3 * MINUTE);
    expect(statuses(expired)).toEqual([
      "completed",
      "not_started",
      "not_started",
      "not_started",
      "not_started",
    ]);
    expect(expired.activeStepId).toBe("mark");
    expect(expired.timer).toEqual({ status: "idle" });
  });

  it("completes exactly once, however late or often it is checked", () => {
    const running = startTimer(fresh(), T0);
    const expired = reconcile(running, T0 + 5 * 60 * MINUTE);
    expect(summarize(expired).completed).toBe(1);
    expect(reconcile(expired, T0 + 6 * 60 * MINUTE)).toBe(expired);
  });

  it("does not complete anything before the end timestamp", () => {
    const running = startTimer(fresh(), T0);
    expect(reconcile(running, T0 + 3 * MINUTE - 1)).toBe(running);
  });

  it("settles an expired timer before applying a late pause", () => {
    const late = pauseTimer(startTimer(fresh(), T0), T0 + 4 * MINUTE);
    expect(statuses(late)[0]).toBe("completed");
    expect(late.timer).toEqual({ status: "idle" });
  });
});

describe("skip", () => {
  it("marks the step skipped, not completed, and moves on", () => {
    const skipped = skipStep(startTimer(fresh(), T0), T0 + MINUTE);
    expect(statuses(skipped)[0]).toBe("skipped");
    expect(skipped.activeStepId).toBe("mark");
    expect(skipped.timer).toEqual({ status: "idle" });
    expect(summarize(skipped)).toMatchObject({ completed: 0, skipped: 1, percent: 0 });
  });

  it("cannot be completed afterwards by the timer it stopped", () => {
    const skipped = skipStep(startTimer(fresh(), T0), T0 + MINUTE);
    const later = reconcile(skipped, T0 + 10 * MINUTE);
    expect(later).toBe(skipped);
    expect(summarize(later).completed).toBe(0);
  });

  it("wraps round to an earlier unfinished step, then leaves no current step", () => {
    let record = selectStep(fresh(), "correct", T0);
    record = skipStep(record, T0);
    expect(record.activeStepId).toBe("listen");

    for (let i = 0; i < 4; i++) record = skipStep(record, T0);
    expect(record.activeStepId).toBeNull();
    expect(summarize(record)).toMatchObject({ skipped: 5, routineCompleted: false });
    expect(skipStep(record, T0)).toBe(record);
    expect(startTimer(record, T0)).toBe(record);
  });
});

describe("manual completion", () => {
  it("stops the running timer when the active step is checked", () => {
    const checked = setStepCompleted(startTimer(fresh(), T0), "listen", true, T0 + MINUTE);
    expect(statuses(checked)[0]).toBe("completed");
    expect(checked.timer).toEqual({ status: "idle" });
    expect(checked.activeStepId).toBe("mark");

    // The old end time passing must not complete the next step.
    expect(reconcile(checked, T0 + 10 * MINUTE)).toBe(checked);
  });

  it("leaves the active step's timer alone when a different step is checked", () => {
    const running = startTimer(fresh(), T0);
    const checked = setStepCompleted(running, "perform", true, T0 + MINUTE);
    expect(statuses(checked)[2]).toBe("completed");
    expect(checked.activeStepId).toBe("listen");
    expect(checked.timer).toEqual(running.timer);
  });

  it("can be undone, which also clears the routine-completed mark", () => {
    let record = fresh();
    for (const step of STEPS) record = setStepCompleted(record, step.id, true, T0);
    expect(record.routineCompletedAtEpochMs).toBe(T0);
    expect(record.activeStepId).toBeNull();
    expect(summarize(record)).toMatchObject({ completed: 5, percent: 100, routineCompleted: true });

    const unchecked = setStepCompleted(record, "perform", false, T0 + MINUTE);
    expect(statuses(unchecked)[2]).toBe("not_started");
    expect(unchecked.activeStepId).toBe("perform");
    expect(unchecked.routineCompletedAtEpochMs).toBeNull();
    expect(summarize(unchecked)).toMatchObject({ completed: 4, percent: 80 });
  });

  it("turns a skipped step into a completed one when checked", () => {
    const checked = setStepCompleted(skipStep(fresh(), T0), "listen", true, T0);
    expect(statuses(checked)[0]).toBe("completed");
    expect(summarize(checked)).toMatchObject({ completed: 1, skipped: 0 });
  });

  it("does not count a routine with skipped steps as fully completed", () => {
    let record = skipStep(fresh(), T0);
    for (const step of STEPS.slice(1)) record = setStepCompleted(record, step.id, true, T0);
    expect(summarize(record)).toMatchObject({ completed: 4, skipped: 1, routineCompleted: false });
    expect(record.routineCompletedAtEpochMs).toBeNull();
  });
});

describe("choosing another step", () => {
  it("stops the timer of the step being left", () => {
    const moved = selectStep(startTimer(fresh(), T0), "perform", T0 + MINUTE);
    expect(moved.activeStepId).toBe("perform");
    expect(moved.timer).toEqual({ status: "idle" });
    expect(statuses(moved)[0]).toBe("not_started");
    expect(remainingMs(moved, T0 + MINUTE)).toBe(4 * MINUTE);
  });

  it("un-skips a skipped step and refuses a completed one", () => {
    const skipped = skipStep(fresh(), T0);
    const back = selectStep(skipped, "listen", T0);
    expect(statuses(back)[0]).toBe("not_started");
    expect(back.activeStepId).toBe("listen");

    const completed = setStepCompleted(fresh(), "listen", true, T0);
    expect(selectStep(completed, "listen", T0)).toBe(completed);
  });
});

describe("progress", () => {
  it("counts completed steps only", () => {
    let record = setStepCompleted(fresh(), "listen", true, T0);
    record = setStepCompleted(record, "mark", true, T0);
    record = skipStep(record, T0);
    expect(summarize(record)).toEqual({
      total: 5,
      completed: 2,
      skipped: 1,
      percent: 40,
      routineCompleted: false,
    });
  });
});

describe("config changes", () => {
  it("returns the same record when the config still matches", () => {
    const record = fresh();
    expect(syncWithConfig(record, STEPS, T0)).toBe(record);
  });

  it("keeps statuses and adopts new durations and steps", () => {
    const done = setStepCompleted(fresh(), "listen", true, T0);
    const changed = [
      { ...STEPS[0], durationSeconds: 60 },
      STEPS[2],
      { id: "cooldown", title: "Cool down", instruction: "", durationSeconds: 30, tools: "" },
    ];
    const synced = syncWithConfig(done, changed, T0);
    expect(synced.steps).toEqual([
      { id: "listen", title: "Listen and observe", durationSeconds: 60, status: "completed" },
      { id: "perform", title: "Perform the monologue", durationSeconds: 240, status: "not_started" },
      { id: "cooldown", title: "Cool down", durationSeconds: 30, status: "not_started" },
    ]);
    // "mark" was current but no longer exists.
    expect(synced.activeStepId).toBe("perform");
  });
});

describe("the monologue a round is on", () => {
  const KNOCKS = { id: "m1", title: "The one who knocks" };
  const BLINDERS = { id: "m2", title: "By order" };
  /** Every step of the round on screen completed. */
  const completeAll = (record: DailyPracticeRecord) =>
    STEPS.reduce((current, step) => setStepCompleted(current, step.id, true, T0), record);

  it("starts with none, and choosing one is not progress", () => {
    const record = fresh();
    expect(record.monologue).toBeNull();
    expect(record.earlierRounds).toEqual([]);

    const chosen = setMonologue(record, KNOCKS, T0);
    expect(chosen.monologue).toEqual(KNOCKS);
    // A day on which a monologue was only looked at leaves nothing to save.
    expect(isPristine(chosen)).toBe(true);
    expect(statuses(chosen)).toEqual(statuses(record));
  });

  it("returns the same record when the monologue is already the one", () => {
    const chosen = setMonologue(fresh(), KNOCKS, T0);
    expect(setMonologue(chosen, { ...KNOCKS }, T0)).toBe(chosen);
  });

  it("follows another choice freely until the round has been started", () => {
    const chosen = setMonologue(fresh(), KNOCKS, T0);
    expect(setMonologue(chosen, BLINDERS, T0).monologue).toEqual(BLINDERS);
  });

  it("stays on its monologue once the round is under way", () => {
    const started = startTimer(setMonologue(fresh(), KNOCKS, T0), T0);
    expect(setMonologue(started, BLINDERS, T0 + SECOND)).toBe(started);

    const ticked = setStepCompleted(setMonologue(fresh(), KNOCKS, T0), "listen", true, T0);
    expect(setMonologue(ticked, BLINDERS, T0).monologue).toEqual(KNOCKS);
  });

  it("takes a monologue at any point if it had none, as a day saved by an earlier version", () => {
    const underWay = setStepCompleted(fresh(), "listen", true, T0);
    const attached = setMonologue(underWay, KNOCKS, T0);
    expect(attached.monologue).toEqual(KNOCKS);
    expect(statuses(attached)).toEqual(statuses(underWay));
  });

  it("brings the saved title up to date without touching anything else", () => {
    const ticked = setStepCompleted(setMonologue(fresh(), KNOCKS, T0), "listen", true, T0);
    const renamed = setMonologue(ticked, { id: "m1", title: "I am the danger" }, T0);
    expect(renamed.monologue).toEqual({ id: "m1", title: "I am the danger" });
    expect(statuses(renamed)).toEqual(statuses(ticked));
  });

  it("switching abandons the round on screen and keeps the rounds before it", () => {
    const first = completeAll(setMonologue(fresh(), KNOCKS, T0));
    const second = skipStep(startNextRound(first, KNOCKS, STEPS, T0), T0);
    const running = startTimer(second, T0);

    const switched = switchMonologue(running, BLINDERS, STEPS, T0 + SECOND);

    expect(switched.monologue).toEqual(BLINDERS);
    expect(isRoundUntouched(switched)).toBe(true);
    expect(switched.timer).toEqual({ status: "idle" });
    expect(switched.earlierRounds).toEqual(running.earlierRounds);
  });
});

describe("practising again the same day", () => {
  const KNOCKS = { id: "m1", title: "The one who knocks" };
  const BLINDERS = { id: "m2", title: "By order" };
  const completeAll = (record: DailyPracticeRecord, atMs = T0) =>
    STEPS.reduce((current, step) => setStepCompleted(current, step.id, true, atMs), record);

  it("is not offered while a step is still to do", () => {
    const partial = setStepCompleted(setMonologue(fresh(), KNOCKS, T0), "listen", true, T0);
    expect(isRoundFinished(partial)).toBe(false);
    expect(startNextRound(partial, KNOCKS, STEPS, T0)).toBe(partial);
  });

  it("files the finished round and starts a fresh one", () => {
    const done = completeAll(setMonologue(fresh(), KNOCKS, T0), T0 + MINUTE);
    expect(isRoundFinished(done)).toBe(true);

    const again = startNextRound(done, KNOCKS, STEPS, T0 + 2 * MINUTE);

    expect(again.earlierRounds).toEqual([
      { monologue: KNOCKS, completed: 5, skipped: 0, total: 5, finishedAtEpochMs: T0 + MINUTE },
    ]);
    expect(isRoundUntouched(again)).toBe(true);
    expect(again.activeStepId).toBe("listen");
    expect(again.monologue).toEqual(KNOCKS);
    // The day now holds a finished round, so it is worth saving even with nothing new done.
    expect(isPristine(again)).toBe(false);
  });

  it("counts a round with skipped steps as finished, but not as a full routine", () => {
    let record = setMonologue(fresh(), KNOCKS, T0);
    for (const step of STEPS.slice(0, 3)) record = setStepCompleted(record, step.id, true, T0);
    record = skipStep(skipStep(record, T0), T0);
    expect(isRoundFinished(record)).toBe(true);

    const again = startNextRound(record, KNOCKS, STEPS, T0);
    expect(again.earlierRounds[0]).toMatchObject({ completed: 3, skipped: 2, total: 5 });
    expect(summarizeDay(again)).toMatchObject({ rounds: 1, fullRounds: 0 });
  });

  it("can be on a different monologue", () => {
    const done = completeAll(setMonologue(fresh(), KNOCKS, T0));
    const again = startNextRound(done, BLINDERS, STEPS, T0);
    expect(again.monologue).toEqual(BLINDERS);
    expect(again.earlierRounds[0].monologue).toEqual(KNOCKS);
  });

  it("keeps the day's routine done however little of the extra round is done", () => {
    const done = completeAll(setMonologue(fresh(), KNOCKS, T0));
    const again = setStepCompleted(startNextRound(done, BLINDERS, STEPS, T0), "listen", true, T0);

    // The round on screen is 1 of 5...
    expect(summarize(again)).toMatchObject({ completed: 1, routineCompleted: false });
    // ...but the day shows its best round, and both monologues.
    expect(summarizeDay(again)).toEqual({
      rounds: 2,
      fullRounds: 1,
      best: { total: 5, completed: 5, skipped: 0, percent: 100, routineCompleted: true },
      monologues: ["The one who knocks", "By order"],
    });
  });

  it("does not count an extra round that was never begun", () => {
    const done = completeAll(setMonologue(fresh(), KNOCKS, T0));
    const again = startNextRound(done, KNOCKS, STEPS, T0);
    expect(summarizeDay(again)).toMatchObject({ rounds: 1, fullRounds: 1, monologues: [KNOCKS.title] });
  });

  it("describes a day with a single round as that round", () => {
    const partial = setStepCompleted(setMonologue(fresh(), KNOCKS, T0), "listen", true, T0);
    expect(summarizeDay(partial)).toEqual({
      rounds: 1,
      fullRounds: 0,
      best: summarize(partial),
      monologues: [KNOCKS.title],
    });
    // A day saved before monologues were chosen here names none.
    expect(summarizeDay(setStepCompleted(fresh(), "listen", true, T0)).monologues).toEqual([]);
  });
});
