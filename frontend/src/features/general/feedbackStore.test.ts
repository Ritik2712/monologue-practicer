import { describe, expect, it, vi } from "vitest";

import { ApiError, type GeneralApi } from "./api";
import { createFeedbackStore, SUMMARY_POLL_MS } from "./feedbackStore";
import type {
  Calibration,
  CalibrationChange,
  FeedbackItem,
  FeedbackSummary,
  FeedbackUpdate,
  JobStatus,
} from "./types";

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

const calibration = (version = 1, adaptive = true) =>
  ({ version, adaptive, state: "calibrating", settings: [], changes: [] }) as unknown as Calibration;
const item = (id: string, category = "pause_false") =>
  ({ id, category, targetId: "pause-1", message: "Saved." }) as FeedbackItem;
const adjustment = (version: number) =>
  ({ version, cause: "auto", setting: "min_pause_ms", newValue: 400 }) as CalibrationChange;
const update = (items: FeedbackItem[], version = 1, adjustments: CalibrationChange[] = []) =>
  ({ items, adjustments, calibration: calibration(version) }) satisfies FeedbackUpdate;

const summaryJob = (status: JobStatus["status"]) =>
  ({ jobId: "job-1", kind: "summary", status, canCancel: true }) as JobStatus;
const summary = (overrides: Partial<FeedbackSummary> = {}) =>
  ({
    feedbackCount: 6,
    facts: [{ id: "f1", text: "6 pieces of feedback in all, on 2 recordings." }],
    notes: [{ about: "a pause you said the app missed", text: "a clear breath here" }],
    noteCount: 6,
    pickableNotes: 6,
    minNotes: 5,
    picked: null,
    job: null,
    ...overrides,
  }) satisfies FeedbackSummary;
const picked = (text: string) =>
  ({ notes: [{ about: "a pause you said the app missed", text }], stale: false }) as unknown as FeedbackSummary["picked"];

function setup() {
  const timers: { callback: () => void; ms: number }[] = [];
  const api = {
    getFeedbackSummary: vi.fn().mockResolvedValue(summary()),
    requestFeedbackSummary: vi.fn().mockResolvedValue(summary({ job: summaryJob("queued") })),
    cancelJob: vi.fn().mockResolvedValue(summaryJob("cancelled")),
    getFeedback: vi.fn().mockResolvedValue(update([])),
    giveFeedback: vi.fn().mockResolvedValue(update([item("fb-1")])),
    deleteFeedback: vi.fn().mockResolvedValue(update([])),
    getCalibration: vi.fn().mockResolvedValue(calibration()),
    undoCalibration: vi.fn().mockResolvedValue(calibration(3)),
    resetCalibration: vi.fn().mockResolvedValue(calibration(4)),
    setAdaptive: vi.fn().mockResolvedValue(calibration(1, false)),
  };
  const store = createFeedbackStore(api as unknown as GeneralApi, (callback, ms) => {
    const timer = { callback, ms };
    timers.push(timer);
    return () => {
      const index = timers.indexOf(timer);
      if (index >= 0) timers.splice(index, 1);
    };
  });
  /** Fires the one pending check on a summary being written and waits for its answer. */
  async function tick() {
    expect(timers).toHaveLength(1);
    timers.shift()?.callback();
    await settle();
  }
  return { store, api, timers, tick, state: () => store.getSnapshot() };
}

describe("showing the feedback of the result on view", () => {
  it("loads the feedback and the calibration together", async () => {
    const { store, api, state } = setup();
    api.getFeedback.mockResolvedValue(update([item("fb-1")], 2));

    store.watch("analysis-1");
    expect(state()).toMatchObject({ analysisId: "analysis-1", status: "loading", items: [] });
    await settle();

    expect(api.getFeedback).toHaveBeenCalledWith("analysis-1");
    expect(state()).toMatchObject({ status: "ready", items: [{ id: "fb-1" }] });
    expect(state().calibration).toMatchObject({ status: "ready", data: { version: 2 } });
  });

  it("does nothing when asked to watch the same result again", async () => {
    const { store, api } = setup();
    store.watch("analysis-1");
    store.watch("analysis-1");
    await settle();
    expect(api.getFeedback).toHaveBeenCalledTimes(1);
  });

  it("drops an answer about a result the user has since left", async () => {
    const { store, api, state } = setup();
    let answerFirst: (value: FeedbackUpdate) => void = () => {};
    api.getFeedback
      .mockReturnValueOnce(new Promise((resolve) => (answerFirst = resolve)))
      .mockResolvedValueOnce(update([item("fb-second")]));

    store.watch("analysis-1");
    store.watch("analysis-2");
    await settle();
    answerFirst(update([item("fb-first")], 9));
    await settle();

    expect(state().items).toMatchObject([{ id: "fb-second" }]);
    // The calibration is the app's, not the result's, so the newer answer is still used.
    expect(state().calibration).toMatchObject({ data: { version: 9 } });
  });

  it("says why when the feedback cannot be loaded, and clears when nothing is on view", async () => {
    const { store, api, state } = setup();
    api.getFeedback.mockRejectedValue(new ApiError("unreachable", "No backend.", 0));

    store.watch("analysis-1");
    await settle();
    expect(state()).toMatchObject({ status: "error", message: "No backend." });

    store.watch(null);
    expect(state()).toMatchObject({ analysisId: null, status: "idle", items: [], message: null });
  });
});

describe("giving feedback", () => {
  it("saves it against the result on view and shows what came back", async () => {
    const { store, api, state } = setup();
    store.watch("analysis-1");
    await settle();

    store.give({ category: "pause_false", targetId: "pause-1" });
    expect(state().saving).toBe(true);
    await settle();

    expect(api.giveFeedback).toHaveBeenCalledWith("analysis-1", {
      category: "pause_false",
      targetId: "pause-1",
    });
    expect(state()).toMatchObject({ saving: false, error: null, items: [{ id: "fb-1" }] });
  });

  it("announces a setting that the feedback has just moved, until it is dismissed", async () => {
    const { store, api, state } = setup();
    api.giveFeedback.mockResolvedValue(update([item("fb-3")], 2, [adjustment(2)]));
    store.watch("analysis-1");
    await settle();

    store.give({ category: "pause_missed", targetId: "seg-1", atSeconds: 1.2 });
    await settle();

    expect(state().adjustments).toMatchObject([{ version: 2, newValue: 400 }]);
    expect(state().calibration).toMatchObject({ data: { version: 2 } });

    store.dismissAdjustments();
    expect(state().adjustments).toEqual([]);
  });

  it("keeps what was there and says why when a save fails", async () => {
    const { store, api, state } = setup();
    api.getFeedback.mockResolvedValue(update([item("fb-1")]));
    api.giveFeedback.mockRejectedValue(new ApiError("unknown_target", "No such pause.", 404));
    store.watch("analysis-1");
    await settle();

    store.give({ category: "pause_false", targetId: "pause-9" });
    await settle();

    expect(state()).toMatchObject({ saving: false, error: "No such pause.", items: [{ id: "fb-1" }] });
    store.dismissError();
    expect(state().error).toBeNull();
  });

  it("does nothing when no result is on view", () => {
    const { store, api } = setup();
    store.give({ category: "wpm_too_high" });
    store.remove("fb-1");
    expect(api.giveFeedback).not.toHaveBeenCalled();
    expect(api.deleteFeedback).not.toHaveBeenCalled();
  });

  it("takes feedback back", async () => {
    const { store, api, state } = setup();
    api.getFeedback.mockResolvedValue(update([item("fb-1")]));
    store.watch("analysis-1");
    await settle();

    store.remove("fb-1");
    await settle();

    expect(api.deleteFeedback).toHaveBeenCalledWith("fb-1");
    expect(state().items).toEqual([]);
  });

  it("stays busy until every save in flight has finished", async () => {
    const { store, api, state } = setup();
    let finishFirst: (value: FeedbackUpdate) => void = () => {};
    api.giveFeedback
      .mockReturnValueOnce(new Promise((resolve) => (finishFirst = resolve)))
      .mockResolvedValueOnce(update([item("fb-2")]));
    store.watch("analysis-1");
    await settle();

    store.give({ category: "pause_false", targetId: "pause-1" });
    store.give({ category: "pause_false", targetId: "pause-2" });
    await settle();
    expect(state().saving).toBe(true);

    finishFirst(update([item("fb-1"), item("fb-2")]));
    await settle();
    expect(state().saving).toBe(false);
  });
});

describe("the calibration", () => {
  it("can be loaded without any result on view", async () => {
    const { store, api, state } = setup();
    api.getCalibration.mockResolvedValue(calibration(5));

    store.loadCalibration();
    await settle();

    expect(state().calibration).toMatchObject({ status: "ready", data: { version: 5 } });
  });

  it("keeps the last good answer when a later check fails", async () => {
    const { store, api, state } = setup();
    store.loadCalibration();
    await settle();
    api.getCalibration.mockRejectedValue(new ApiError("unreachable", "No backend.", 0));

    store.loadCalibration();
    await settle();

    expect(state().calibration).toMatchObject({ status: "ready", data: { version: 1 } });
  });

  it("says why when it could never be loaded", async () => {
    const { store, api, state } = setup();
    api.getCalibration.mockRejectedValue(new ApiError("unreachable", "No backend.", 0));

    store.loadCalibration();
    await settle();

    expect(state().calibration).toEqual({ status: "error", message: "No backend." });
  });

  it.each([
    ["undo", "undoCalibration", 3],
    ["reset", "resetCalibration", 4],
  ] as const)("%s shows the new calibration and rewords the feedback on view", async (action, call, version) => {
    const { store, api, state } = setup();
    api.giveFeedback.mockResolvedValue(update([item("fb-1")], 2, [adjustment(2)]));
    store.watch("analysis-1");
    await settle();
    store.give({ category: "pause_missed", targetId: "seg-1", atSeconds: 1.2 });
    await settle();
    api.getFeedback.mockResolvedValue(update([{ ...item("fb-1"), message: "No longer in effect." }], version));

    store[action]();
    await settle();

    expect(api[call]).toHaveBeenCalledTimes(1);
    expect(state().calibration).toMatchObject({ data: { version } });
    // The notice about the adjustment goes: it is no longer what is in force.
    expect(state().adjustments).toEqual([]);
    expect(state().items[0].message).toBe("No longer in effect.");
  });

  it("switches automatic adjustment off and on", async () => {
    const { store, api, state } = setup();

    store.setAdaptive(false);
    await settle();

    expect(api.setAdaptive).toHaveBeenCalledWith(false);
    expect(state().calibration).toMatchObject({ data: { adaptive: false } });
  });

  it("says why when a change to the calibration is refused", async () => {
    const { store, api, state } = setup();
    api.undoCalibration.mockRejectedValue(
      new ApiError("nothing_to_undo", "There is no adjustment to undo.", 409),
    );

    store.undo();
    await settle();

    expect(state()).toMatchObject({ saving: false, error: "There is no adjustment to undo." });
  });
});

describe("the summary of all the feedback", () => {
  async function withSummary() {
    const context = setup();
    context.store.loadSummary();
    await settle();
    return context;
  }

  it("loads the facts the app has counted", async () => {
    const { store, api, state, timers } = setup();

    store.loadSummary();
    expect(state().summary).toEqual({ status: "loading" });
    await settle();

    expect(api.getFeedbackSummary).toHaveBeenCalledTimes(1);
    expect(state().summary).toMatchObject({
      status: "ready",
      asking: false,
      error: null,
      data: { feedbackCount: 6, facts: [{ id: "f1" }], notes: [{ text: "a clear breath here" }] },
    });
    // The AI model is not being asked anything, so there is nothing to keep checking.
    expect(timers).toHaveLength(0);
  });

  it("says so when the facts cannot be loaded", async () => {
    const { store, api, state } = setup();
    api.getFeedbackSummary.mockRejectedValue(new ApiError("unreachable", "No backend.", 0));

    store.loadSummary();
    await settle();

    expect(state().summary).toEqual({ status: "error", message: "No backend." });
  });

  it("asks the AI model, then checks every two seconds until it has picked", async () => {
    const { store, api, state, timers, tick } = await withSummary();

    store.askForSummary();
    expect(state().summary).toMatchObject({ asking: true });
    await settle();

    expect(api.requestFeedbackSummary).toHaveBeenCalledTimes(1);
    expect(state().summary).toMatchObject({ asking: false, data: { job: { status: "queued" } } });
    expect(timers.map((timer) => timer.ms)).toEqual([SUMMARY_POLL_MS]);

    api.getFeedbackSummary.mockResolvedValue(summary({ job: summaryJob("running") }));
    await tick();
    expect(state().summary).toMatchObject({ data: { job: { status: "running" } } });

    api.getFeedbackSummary.mockResolvedValue(summary({ picked: picked("a clear breath here") }));
    await tick();
    expect(state().summary).toMatchObject({
      data: { job: null, picked: { notes: [{ text: "a clear breath here" }] } },
    });
    expect(timers).toHaveLength(0);
  });

  it("ignores a second click while the first request is still on its way", async () => {
    const { store, api } = await withSummary();
    api.requestFeedbackSummary.mockReturnValue(new Promise(() => {}));

    store.askForSummary();
    store.askForSummary();

    expect(api.requestFeedbackSummary).toHaveBeenCalledTimes(1);
  });

  it("keeps the facts on screen and says why when the request is refused", async () => {
    const { store, api, state } = await withSummary();
    api.requestFeedbackSummary.mockRejectedValue(
      new ApiError("too_few_notes", "There is nothing to pick from yet.", 409),
    );

    store.askForSummary();
    await settle();

    expect(state().summary).toMatchObject({
      status: "ready",
      asking: false,
      error: "There is nothing to pick from yet.",
      data: { feedbackCount: 6 },
    });
  });

  it("shows why the AI model could not be asked, and stops checking", async () => {
    const { store, api, state, timers, tick } = await withSummary();
    store.askForSummary();
    await settle();
    api.getFeedbackSummary.mockResolvedValue(
      summary({
        job: {
          ...summaryJob("failed"),
          error: { code: "not_running", message: "Ollama is not running.", retryable: false },
        },
      }),
    );

    await tick();

    expect(state().summary).toMatchObject({
      data: { job: { status: "failed", error: { code: "not_running" } } },
    });
    expect(timers).toHaveLength(0);
  });

  it("keeps checking when the backend is briefly away while the AI model is being asked", async () => {
    const { store, api, state, timers, tick } = await withSummary();
    store.askForSummary();
    await settle();
    api.getFeedbackSummary.mockRejectedValueOnce(new ApiError("unreachable", "No backend.", 0));

    await tick();

    // The last good answer stays on screen, and another check is on its way.
    expect(state().summary).toMatchObject({ status: "ready", data: { job: { status: "queued" } } });
    expect(timers).toHaveLength(1);
  });

  it("stops a request to the AI model that is under way", async () => {
    const { store, api, state, timers } = await withSummary();
    store.askForSummary();
    await settle();
    api.getFeedbackSummary.mockResolvedValue(summary());

    store.cancelSummary();
    await settle();

    expect(api.cancelJob).toHaveBeenCalledWith("job-1");
    expect(state().summary).toMatchObject({ asking: false, data: { job: null } });
    expect(timers).toHaveLength(0);
  });

  it("counts again whenever feedback is given, taken back, or the settings change", async () => {
    const { store, api } = await withSummary();
    store.watch("analysis-1");
    await settle();
    const before = api.getFeedbackSummary.mock.calls.length;

    store.give({ category: "pause_false", targetId: "pause-1" });
    await settle();
    store.remove("fb-1");
    await settle();
    store.watch(null);
    store.reset();
    await settle();

    expect(api.getFeedbackSummary.mock.calls.length - before).toBe(3);
  });

  it("does not count on its own account before the panel has asked for the facts", async () => {
    const { store, api } = setup();
    store.watch("analysis-1");
    await settle();

    store.give({ category: "pause_false", targetId: "pause-1" });
    await settle();

    expect(api.getFeedbackSummary).not.toHaveBeenCalled();
  });

  it("lets a newer answer win over an older one that arrives late", async () => {
    const { store, api, state } = await withSummary();
    let answerOld: (value: FeedbackSummary) => void = () => {};
    api.getFeedbackSummary
      .mockReturnValueOnce(new Promise((resolve) => (answerOld = resolve)))
      .mockResolvedValueOnce(summary({ feedbackCount: 9 }));

    store.loadSummary();
    store.loadSummary();
    await settle();
    answerOld(summary({ feedbackCount: 8 }));
    await settle();

    expect(state().summary).toMatchObject({ data: { feedbackCount: 9 } });
  });
});
