import { describe, expect, it, vi } from "vitest";

import { ApiError, NO_MONOLOGUE, type GeneralApi } from "./api";
import {
  ACTIVE_JOB_KEY,
  createGeneralStore,
  HISTORY_LIMIT,
  LEGACY_SELECTED_REFERENCE_KEY,
  MAX_POLL_MS,
  POLL_MS,
  TAKES_LIMIT,
  type Submission,
} from "./generalStore";
import type {
  AnalysisList,
  AnalysisResult,
  AnalysisSummary,
  Comparison,
  JobStatus,
  Monologue,
} from "./types";

function job(overrides: Partial<JobStatus> = {}): JobStatus {
  return {
    jobId: "job-1",
    kind: "analysis",
    role: "take",
    status: "queued",
    stage: null,
    cancelRequested: false,
    error: null,
    analysisId: null,
    canRetry: false,
    canCancel: true,
    queuePosition: 0,
    workerAlive: true,
    attempt: 0,
    createdAt: "2026-10-11T04:00:00Z",
    startedAt: null,
    finishedAt: null,
    ...overrides,
  };
}

const analysis = (id = "analysis-1") =>
  ({ analysisId: id, role: "take", audioRetained: false }) as AnalysisResult;
const summary = (id: string, audioRetained = false) =>
  ({ analysisId: id, role: "take", audioRetained, metrics: {} }) as AnalysisSummary;
const referenceResult = (id: string) =>
  ({ analysisId: id, role: "reference", title: "The original", audioRetained: true }) as AnalysisResult;
/** A monologue whose original recording, in its newest revision, is `referenceId`. */
const monologue = (id: string, referenceId: string, takeCount = 0) =>
  ({
    monologueId: id,
    referenceId,
    title: "The original",
    audioRetained: true,
    takeCount,
    lastTakeAt: null,
  }) as Monologue;
/** A take recorded for a monologue. In these tests its ID says which: "m1:take-1". */
const takeOf = (id: string) =>
  ({
    analysisId: id,
    role: "take",
    monologueId: id.split(":")[0],
    audioRetained: false,
  }) as AnalysisResult;
const comparison = (takeId: string, referenceId: string) =>
  ({ takeId, referenceId, differences: [] }) as unknown as Comparison;

const submission: Submission = {
  audio: new Blob(["audio"]),
  filename: "take.webm",
  profile: "walter_white",
  language: "hi",
  retainAudio: false,
  previewUrl: "blob:take-1",
};

/** Lets every promise that is ready to resolve do so. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function setup(stored: Record<string, string> = {}) {
  const api = {
    getHealth: vi.fn(),
    getOptions: vi.fn().mockResolvedValue({ profiles: [], languages: [] }),
    submitAnalysis: vi.fn().mockResolvedValue(job()),
    getJob: vi.fn().mockResolvedValue(job()),
    cancelJob: vi.fn(),
    retryJob: vi.fn(),
    getAnalysis: vi.fn().mockResolvedValue(analysis()),
    requestCoaching: vi.fn(),
    getComparison: vi.fn(),
    getWaveform: vi.fn(),
    listAnalyses: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    listMonologues: vi.fn().mockResolvedValue({ items: [] }),
    deleteMonologue: vi.fn().mockResolvedValue({ deletedReferences: 1, deletedTakes: 0 }),
    deleteAnalysis: vi.fn().mockResolvedValue(undefined),
    deleteAnalysisAudio: vi.fn().mockResolvedValue(undefined),
    clearAnalyses: vi.fn().mockResolvedValue({ deletedAnalyses: 0, deletedJobs: 0 }),
    analysisAudioUrl: (id: string) => `http://api/analyses/${id}/audio`,
    getFeedback: vi.fn(),
    giveFeedback: vi.fn(),
    deleteFeedback: vi.fn(),
    getCalibration: vi.fn(),
    undoCalibration: vi.fn(),
    resetCalibration: vi.fn(),
    setAdaptive: vi.fn(),
    correctTranscript: vi.fn(),
    requestReanalysis: vi.fn(),
    getFeedbackSummary: vi.fn(),
    requestFeedbackSummary: vi.fn(),
  } satisfies Record<keyof GeneralApi, unknown>;

  const timers: { callback: () => void; ms: number }[] = [];
  const storage = new Map(Object.entries(stored));
  const revoked: string[] = [];
  let keys = 0;
  const store = createGeneralStore({
    api: api as unknown as GeneralApi,
    schedule: (callback, ms) => {
      const timer = { callback, ms };
      timers.push(timer);
      return () => {
        const index = timers.indexOf(timer);
        if (index >= 0) timers.splice(index, 1);
      };
    },
    newKey: () => `key-${++keys}`,
    getStorage: () => ({
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => void storage.set(key, value),
      removeItem: (key) => void storage.delete(key),
    }),
    revokeUrl: (url) => void revoked.push(url),
  });

  /** Fires the one pending status check and waits for its answer. */
  async function tick() {
    expect(timers).toHaveLength(1);
    timers.shift()?.callback();
    await settle();
  }

  return { store, api, timers, storage, revoked, tick, run: () => store.getSnapshot().run };
}

describe("submitting and following a job", () => {
  it("goes from upload to result, polling once a second", async () => {
    const { store, api, timers, storage, tick, run } = setup();
    api.listAnalyses.mockResolvedValue({ items: [summary("analysis-1")], total: 1 });

    expect(store.submit(submission)).toBe(true);
    expect(run().phase).toBe("submitting");
    await settle();

    expect(api.submitAnalysis).toHaveBeenCalledWith({
      audio: submission.audio,
      filename: "take.webm",
      profile: "walter_white",
      language: "hi",
      retainAudio: false,
      idempotencyKey: "key-1",
    });
    expect(run()).toMatchObject({ phase: "tracking", contact: "ok", job: { status: "queued" } });
    expect(storage.get(ACTIVE_JOB_KEY)).toBe("job-1");
    expect(timers.map((timer) => timer.ms)).toEqual([POLL_MS]);

    api.getJob.mockResolvedValue(job({ status: "running", stage: "transcribing" }));
    await tick();
    expect(run()).toMatchObject({ phase: "tracking", job: { stage: "transcribing" } });

    api.getJob.mockResolvedValue(job({ status: "succeeded", analysisId: "analysis-1" }));
    await tick();

    expect(run()).toMatchObject({ phase: "done", analysisId: "analysis-1" });
    expect(store.getSnapshot().viewed).toMatchObject({
      status: "ready",
      analysis: { analysisId: "analysis-1" },
    });
    // The recording submitted in this session can be played back with the result.
    expect(store.getSnapshot().localAudio).toEqual({ "analysis-1": "blob:take-1" });
    expect(store.getSnapshot().history.items).toHaveLength(1);
    expect(storage.has(ACTIVE_JOB_KEY)).toBe(false);
    expect(timers).toHaveLength(0); // polling has stopped
  });

  it("ignores a second submit while one is in progress", async () => {
    const { store, api } = setup();
    expect(store.submit(submission)).toBe(true);
    expect(store.submit(submission)).toBe(false);
    await settle();
    expect(store.submit(submission)).toBe(false); // still being tracked
    expect(api.submitAnalysis).toHaveBeenCalledTimes(1);
  });

  it("tells every subscriber, and stops after unsubscribing", async () => {
    const { store } = setup();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.submit(submission);
    await settle();
    expect(listener).toHaveBeenCalled();

    unsubscribe();
    listener.mockClear();
    store.dismissNotice();
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("when things go wrong", () => {
  it("shows a refused upload and does not offer to send the same file again", async () => {
    const { store, api, run, storage } = setup();
    api.submitAnalysis.mockRejectedValue(
      new ApiError("file_too_large", "The file is larger than the 50 MB limit.", 413),
    );
    store.submit(submission);
    await settle();

    expect(run()).toEqual({
      phase: "failed",
      job: null,
      error: expect.objectContaining({ code: "file_too_large" }),
      canResubmit: false,
    });
    expect(storage.has(ACTIVE_JOB_KEY)).toBe(false);
  });

  it("can resend after the backend was unreachable, with the same idempotency key", async () => {
    const { store, api, run } = setup();
    api.submitAnalysis.mockRejectedValueOnce(new ApiError("unreachable", "No backend.", 0));
    store.submit(submission);
    await settle();
    expect(run()).toMatchObject({ phase: "failed", canResubmit: true });

    store.resubmit();
    await settle();

    expect(run().phase).toBe("tracking");
    const keys = api.submitAnalysis.mock.calls.map(([request]) => request.idempotencyKey);
    // Same key: if the first upload did arrive, the backend returns that job, not a new one.
    expect(keys).toEqual(["key-1", "key-1"]);
  });

  it("keeps the last status and backs off while the backend is not answering", async () => {
    const { store, api, timers, tick, run } = setup();
    store.submit(submission);
    await settle();
    api.getJob.mockResolvedValue(job({ status: "running", stage: "transcribing" }));
    await tick();

    api.getJob.mockRejectedValue(new ApiError("unreachable", "No backend.", 0));
    const delays: number[] = [];
    for (let attempt = 0; attempt < 4; attempt++) {
      await tick();
      delays.push(timers[0].ms);
    }
    expect(run()).toMatchObject({
      phase: "tracking",
      contact: "lost",
      job: { stage: "transcribing" },
    });
    expect(delays).toEqual([2000, 4000, MAX_POLL_MS, MAX_POLL_MS]);

    api.getJob.mockResolvedValue(job({ status: "running", stage: "measuring_audio" }));
    await tick();
    expect(run()).toMatchObject({ contact: "ok", job: { stage: "measuring_audio" } });
    expect(timers[0].ms).toBe(POLL_MS);
  });

  it("shows why a job failed and can retry it on the server", async () => {
    const { store, api, tick, run } = setup();
    store.submit(submission);
    await settle();
    const failed = job({
      status: "failed",
      canRetry: true,
      canCancel: false,
      error: { code: "speech_model_missing", message: "Download the model.", retryable: true },
    });
    api.getJob.mockResolvedValue(failed);
    await tick();

    expect(run()).toMatchObject({
      phase: "failed",
      error: { code: "speech_model_missing", message: "Download the model." },
      canResubmit: false,
    });

    api.retryJob.mockResolvedValue(job({ status: "queued" }));
    store.retry();
    await settle();
    expect(api.retryJob).toHaveBeenCalledWith("job-1");
    expect(run().phase).toBe("tracking");
  });

  it("does not offer a server retry when the job says it cannot be retried", async () => {
    const { store, api, tick } = setup();
    store.submit(submission);
    await settle();
    api.getJob.mockResolvedValue(
      job({
        status: "failed",
        canRetry: false,
        error: { code: "unreadable_audio", message: "Not audio.", retryable: false },
      }),
    );
    await tick();
    store.retry();
    expect(api.retryJob).not.toHaveBeenCalled();
  });

  it("discarding a failed job deletes its kept audio and clears the run", async () => {
    const { store, api, tick, run, storage } = setup();
    store.submit(submission);
    await settle();
    const failed = job({
      status: "failed",
      canRetry: true,
      error: { code: "unexpected_error", message: "Oops.", retryable: true },
    });
    api.getJob.mockResolvedValue(failed);
    await tick();
    expect(storage.get(ACTIVE_JOB_KEY)).toBe("job-1"); // still retryable after a refresh

    api.cancelJob.mockResolvedValue({ ...failed, canRetry: false });
    store.cancel();
    await settle();
    expect(api.cancelJob).toHaveBeenCalledWith("job-1");
    expect(run()).toEqual({ phase: "idle" });
    expect(storage.has(ACTIVE_JOB_KEY)).toBe(false);
  });

  it("reports a job that has vanished", async () => {
    const { store, api, tick, run } = setup();
    store.submit(submission);
    await settle();
    api.getJob.mockRejectedValue(new ApiError("job_not_found", "No such job.", 404));
    await tick();
    expect(run()).toMatchObject({ phase: "failed", error: { code: "job_not_found" } });
  });
});

describe("cancelling", () => {
  it("shows a running job as still running until the worker has really stopped", async () => {
    const { store, api, tick, run, storage } = setup();
    store.submit(submission);
    await settle();
    api.cancelJob.mockResolvedValue(
      job({ status: "running", stage: "transcribing", cancelRequested: true, canCancel: false }),
    );

    store.cancel();
    await settle();
    expect(run()).toMatchObject({
      phase: "tracking",
      job: { status: "running", cancelRequested: true },
    });

    api.getJob.mockResolvedValue(job({ status: "cancelled", canCancel: false }));
    await tick();
    expect(run()).toMatchObject({ phase: "cancelled" });
    expect(storage.has(ACTIVE_JOB_KEY)).toBe(false);
  });

  it("lets a new recording be submitted afterwards", async () => {
    const { store, api, run } = setup();
    store.submit(submission);
    await settle();
    api.cancelJob.mockResolvedValue(job({ status: "cancelled" }));
    store.cancel();
    await settle();

    store.dismissRun();
    expect(run()).toEqual({ phase: "idle" });
    expect(store.submit(submission)).toBe(true);
    await settle();
    expect(api.submitAnalysis.mock.calls[1][0].idempotencyKey).toBe("key-2");
  });
});

describe("starting up", () => {
  it("loads the form options and the history", async () => {
    const { store, api } = setup();
    api.listAnalyses.mockResolvedValue({ items: [summary("a"), summary("b")], total: 2 });
    store.init();
    store.init(); // a second call does nothing
    await settle();

    expect(api.getOptions).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().options.status).toBe("ready");
    expect(store.getSnapshot().history).toMatchObject({ status: "ready", total: 2 });
    // The history is of the takes that belong to no monologue.
    expect(api.listAnalyses).toHaveBeenCalledWith(HISTORY_LIMIT, "take", NO_MONOLOGUE);
  });

  it("clears the reference that an earlier version remembered between visits", async () => {
    const { store, storage } = setup({ [LEGACY_SELECTED_REFERENCE_KEY]: "ref-1" });
    store.init();
    await settle();

    expect(storage.has(LEGACY_SELECTED_REFERENCE_KEY)).toBe(false);
    expect(store.getSnapshot().selectedReferenceId).toBeNull();
  });

  it("picks up a job that was in progress before the page was refreshed", async () => {
    const { store, api, run } = setup({ [ACTIVE_JOB_KEY]: "job-9" });
    api.getJob.mockResolvedValue(job({ jobId: "job-9", status: "running", stage: "transcribing" }));
    store.init();
    await settle();

    expect(api.getJob).toHaveBeenCalledWith("job-9");
    expect(run()).toMatchObject({ phase: "tracking", job: { jobId: "job-9" } });
  });

  it("forgets a remembered job that no longer exists", async () => {
    const { store, api, storage } = setup({ [ACTIVE_JOB_KEY]: "gone" });
    api.getJob.mockRejectedValue(new ApiError("job_not_found", "No such job.", 404));
    store.init();
    await settle();
    expect(storage.has(ACTIVE_JOB_KEY)).toBe(false);
  });

  it("reports unreachable options and history without throwing", async () => {
    const { store, api } = setup();
    api.getOptions.mockRejectedValue(new ApiError("unreachable", "No backend.", 0));
    api.listAnalyses.mockRejectedValue(new ApiError("unreachable", "No backend.", 0));
    store.init();
    await settle();
    expect(store.getSnapshot().options).toEqual({ status: "error", message: "No backend." });
    expect(store.getSnapshot().history).toMatchObject({ status: "error", message: "No backend." });
  });
});

describe("history", () => {
  async function withResult() {
    const context = setup();
    context.api.listAnalyses.mockResolvedValue({
      items: [summary("analysis-1", true), summary("older")],
      total: 2,
    });
    context.api.getJob.mockResolvedValue(job({ status: "succeeded", analysisId: "analysis-1" }));
    context.store.submit(submission);
    await settle();
    await context.tick();
    return context;
  }

  it("opens an earlier analysis", async () => {
    const { store, api } = setup();
    api.getAnalysis.mockResolvedValue(analysis("older"));
    store.openAnalysis("older");
    expect(store.getSnapshot().viewed).toEqual({ status: "loading", analysisId: "older" });
    await settle();
    expect(store.getSnapshot().viewed).toMatchObject({
      status: "ready",
      analysis: { analysisId: "older" },
    });

    store.closeAnalysis();
    expect(store.getSnapshot().viewed).toEqual({ status: "none" });
  });

  it("reports an analysis that cannot be opened", async () => {
    const { store, api } = setup();
    api.getAnalysis.mockRejectedValue(new ApiError("analysis_not_found", "Gone.", 404));
    store.openAnalysis("missing");
    await settle();
    expect(store.getSnapshot().viewed).toEqual({
      status: "error",
      analysisId: "missing",
      message: "Gone.",
    });
  });

  it("deleting the analysis on screen removes it everywhere", async () => {
    const { store, api, revoked, run } = await withResult();
    api.listAnalyses.mockResolvedValue({ items: [summary("older")], total: 1 });

    store.deleteAnalysis("analysis-1");
    await settle();

    expect(api.deleteAnalysis).toHaveBeenCalledWith("analysis-1");
    const state = store.getSnapshot();
    expect(state.viewed).toEqual({ status: "none" });
    expect(run()).toEqual({ phase: "idle" });
    expect(state.history.items.map((item) => item.analysisId)).toEqual(["older"]);
    expect(state.localAudio).toEqual({});
    expect(revoked).toEqual(["blob:take-1"]);
    expect(state.notice).toEqual({ kind: "info", text: "Analysis deleted." });
  });

  it("deleting only the recording keeps the measurements", async () => {
    const { store, api, revoked } = await withResult();

    store.deleteAudio("analysis-1");
    await settle();

    expect(api.deleteAnalysisAudio).toHaveBeenCalledWith("analysis-1");
    const state = store.getSnapshot();
    expect(state.viewed).toMatchObject({ status: "ready", analysis: { audioRetained: false } });
    expect(state.history.items[0]).toMatchObject({ analysisId: "analysis-1", audioRetained: false });
    // The copy held in the page's memory is dropped as well.
    expect(state.localAudio).toEqual({});
    expect(revoked).toEqual(["blob:take-1"]);
  });

  it("clearing the history empties the screen", async () => {
    const { store, api, run } = await withResult();
    api.clearAnalyses.mockResolvedValue({ deletedAnalyses: 2, deletedJobs: 2 });

    store.clearHistory();
    await settle();

    const state = store.getSnapshot();
    expect(state.history).toMatchObject({ status: "ready", items: [], total: 0 });
    expect(state.viewed).toEqual({ status: "none" });
    expect(run()).toEqual({ phase: "idle" });
    expect(state.notice?.text).toBe("History cleared: 2 analyses deleted.");
  });

  it("clearing the history leaves a job in progress alone", async () => {
    const { store, api, run, timers } = setup();
    store.submit(submission);
    await settle();
    api.clearAnalyses.mockResolvedValue({ deletedAnalyses: 1, deletedJobs: 1 });

    store.clearHistory();
    await settle();

    expect(run().phase).toBe("tracking");
    expect(timers).toHaveLength(1);
    expect(store.getSnapshot().notice?.text).toBe("History cleared: 1 analysis deleted.");
  });

  it("shows a message when a delete fails", async () => {
    const { store, api } = setup();
    api.deleteAnalysis.mockRejectedValue(new ApiError("unreachable", "No backend.", 0));
    store.deleteAnalysis("x");
    await settle();
    expect(store.getSnapshot().notice).toEqual({ kind: "error", text: "No backend." });

    store.dismissNotice();
    expect(store.getSnapshot().notice).toBeNull();
  });
});

describe("writing the coaching again", () => {
  const coachingJob = (overrides: Partial<JobStatus> = {}) =>
    job({ jobId: "job-c", kind: "coaching", analysisId: "analysis-1", ...overrides });

  /** A store with analysis-1 open on screen. */
  async function withOpenAnalysis() {
    const context = setup();
    context.store.openAnalysis("analysis-1");
    await settle();
    context.api.requestCoaching.mockResolvedValue(coachingJob());
    return context;
  }

  it("follows a coaching job and shows the new coaching in place", async () => {
    const { store, api, storage, tick, run } = await withOpenAnalysis();
    const rewritten = { ...analysis(), coaching: { source: "ai" } } as AnalysisResult;

    expect(store.regenerateCoaching("analysis-1")).toBe(true);
    expect(run().phase).toBe("submitting");
    expect(store.getSnapshot()).toMatchObject({ runKind: "coaching", coachingFor: "analysis-1" });
    await settle();

    expect(api.requestCoaching).toHaveBeenCalledWith("analysis-1");
    expect(api.submitAnalysis).not.toHaveBeenCalled(); // no audio is sent again
    expect(run()).toMatchObject({ phase: "tracking", job: { kind: "coaching" } });
    expect(storage.get(ACTIVE_JOB_KEY)).toBe("job-c");

    api.getJob.mockResolvedValue(coachingJob({ status: "running", stage: "generating_feedback" }));
    await tick();
    expect(run()).toMatchObject({ phase: "tracking", job: { stage: "generating_feedback" } });

    api.getJob.mockResolvedValue(coachingJob({ status: "succeeded" }));
    api.getAnalysis.mockResolvedValue(rewritten);
    await tick();

    expect(run()).toMatchObject({ phase: "done", analysisId: "analysis-1" });
    expect(store.getSnapshot().viewed).toEqual({ status: "ready", analysis: rewritten });
    expect(storage.has(ACTIVE_JOB_KEY)).toBe(false);
  });

  it("does nothing while another run is in progress", async () => {
    const { store, api } = await withOpenAnalysis();
    store.submit(submission);
    await settle();

    expect(store.regenerateCoaching("analysis-1")).toBe(false);
    expect(api.requestCoaching).not.toHaveBeenCalled();
    expect(store.getSnapshot().runKind).toBe("analysis");
  });

  it("does not pull the user away from another analysis they opened meanwhile", async () => {
    const { store, api, tick, run } = await withOpenAnalysis();
    store.regenerateCoaching("analysis-1");
    await settle();

    api.getAnalysis.mockResolvedValue(analysis("analysis-2"));
    store.openAnalysis("analysis-2");
    await settle();

    api.getJob.mockResolvedValue(coachingJob({ status: "succeeded" }));
    api.getAnalysis.mockResolvedValue(analysis("analysis-1"));
    await tick();

    expect(run().phase).toBe("done");
    expect(store.getSnapshot().viewed).toMatchObject({ analysis: { analysisId: "analysis-2" } });
  });

  it("says why when the model could not write it, and can try again", async () => {
    const { store, api, tick, run } = await withOpenAnalysis();
    store.regenerateCoaching("analysis-1");
    await settle();

    const error = { code: "not_running", message: "Ollama is not running.", retryable: false };
    api.getJob.mockResolvedValue(coachingJob({ status: "failed", error }));
    await tick();

    expect(run()).toMatchObject({ phase: "failed", error, canResubmit: false });
    expect(store.getSnapshot().coachingFor).toBe("analysis-1");
    // The analysis on screen, with its earlier coaching, is untouched.
    expect(store.getSnapshot().viewed).toMatchObject({ analysis: { analysisId: "analysis-1" } });

    expect(store.regenerateCoaching("analysis-1")).toBe(true);
    await settle();
    expect(api.requestCoaching).toHaveBeenCalledTimes(2);
  });

  it("reports a request that never reached the backend", async () => {
    const { store, api, run } = await withOpenAnalysis();
    api.requestCoaching.mockRejectedValue(new ApiError("unreachable", "No backend.", 0));
    store.regenerateCoaching("analysis-1");
    await settle();

    expect(run()).toMatchObject({
      phase: "failed",
      job: null,
      error: { code: "unreachable", message: "No backend." },
    });
  });

  it("recognises a coaching job picked up after a page refresh", async () => {
    const { store, api } = setup({ [ACTIVE_JOB_KEY]: "job-c" });
    api.getJob.mockResolvedValue(coachingJob({ status: "running", stage: "generating_feedback" }));
    store.init();
    await settle();

    expect(store.getSnapshot()).toMatchObject({ runKind: "coaching", coachingFor: "analysis-1" });
  });

  it("goes back to an ordinary run when a recording is submitted afterwards", async () => {
    const { store, api, tick } = await withOpenAnalysis();
    store.regenerateCoaching("analysis-1");
    await settle();
    api.getJob.mockResolvedValue(coachingJob({ status: "cancelled" }));
    await tick();

    store.submit(submission);
    expect(store.getSnapshot()).toMatchObject({ runKind: "analysis", coachingFor: null });
  });
});

describe("revisions of a recording", () => {
  const revision = (id: string, number: number) =>
    ({ analysisId: id, role: "take", revision: number, audioRetained: false }) as AnalysisResult;

  /** A store with analysis-1 open on screen. */
  async function withOpenAnalysis() {
    const context = setup();
    context.store.openAnalysis("analysis-1");
    await settle();
    return context;
  }

  it("compares with the corrected revision of the original, and leaves the take on view alone", async () => {
    const { store, api } = setup();
    api.listMonologues.mockResolvedValue({ items: [monologue("m1", "ref-1")] });
    api.getAnalysis.mockImplementation((id: string) =>
      Promise.resolve(id.startsWith("ref") ? referenceResult(id) : takeOf(id)),
    );
    api.getComparison.mockImplementation((takeId: string, referenceId: string) =>
      Promise.resolve(comparison(takeId, referenceId)),
    );
    store.init();
    store.watchMonologue("m1");
    store.openAnalysis("m1:take-1");
    await settle();
    expect(api.getComparison).toHaveBeenLastCalledWith("m1:take-1", "ref-1");

    api.correctTranscript.mockResolvedValue({ ...referenceResult("ref-2"), revision: 2 });
    api.listMonologues.mockResolvedValue({ items: [monologue("m1", "ref-2")] });
    store.correctTranscript("ref-1", [{ segmentId: "seg-1", text: "the real words" }]);
    await settle();

    const state = store.getSnapshot();
    expect(state.correction).toEqual({ status: "idle" });
    expect(state.selectedReferenceId).toBe("ref-2");
    expect(state.referenceDetail).toMatchObject({ status: "ready", analysis: { analysisId: "ref-2" } });
    expect(state.viewed).toMatchObject({ status: "ready", analysis: { analysisId: "m1:take-1" } });
    expect(state.notice?.text).toContain("Saved as revision 2 of the original recording");
    // It is still the same monologue, and the take is now compared with the corrected one.
    expect(state.monologues.items).toEqual([monologue("m1", "ref-2")]);
    expect(api.getComparison).toHaveBeenLastCalledWith("m1:take-1", "ref-2");
  });

  it("shows the new revision once the corrected words are saved", async () => {
    const { store, api } = await withOpenAnalysis();
    api.correctTranscript.mockResolvedValue(revision("analysis-2", 2));
    api.listAnalyses.mockResolvedValue({
      items: [summary("analysis-2"), summary("analysis-1")],
      total: 2,
    });
    const corrections = [{ segmentId: "seg-1", text: "the real words" }];

    store.correctTranscript("analysis-1", corrections);
    expect(store.getSnapshot().correction).toEqual({ status: "saving", analysisId: "analysis-1" });
    await settle();

    expect(api.correctTranscript).toHaveBeenCalledWith("analysis-1", corrections);
    const state = store.getSnapshot();
    expect(state.correction).toEqual({ status: "idle" });
    expect(state.viewed).toMatchObject({ status: "ready", analysis: { analysisId: "analysis-2" } });
    expect(state.notice?.text).toContain("Saved as revision 2");
    // Both results are in the history: the earlier one is not replaced.
    expect(state.history.items.map((entry) => entry.analysisId)).toEqual([
      "analysis-2",
      "analysis-1",
    ]);
  });

  it("keeps the corrected result off screen if the user has opened another meanwhile", async () => {
    const { store, api } = await withOpenAnalysis();
    let save: (value: AnalysisResult) => void = () => {};
    api.correctTranscript.mockReturnValue(new Promise((resolve) => (save = resolve)));

    store.correctTranscript("analysis-1", [{ segmentId: "seg-1", text: "words" }]);
    api.getAnalysis.mockResolvedValue(analysis("analysis-9"));
    store.openAnalysis("analysis-9");
    await settle();
    save(revision("analysis-2", 2));
    await settle();

    expect(store.getSnapshot().viewed).toMatchObject({ analysis: { analysisId: "analysis-9" } });
  });

  it("says why when the correction is refused, and leaves the result on view", async () => {
    const { store, api } = await withOpenAnalysis();
    api.correctTranscript.mockRejectedValue(
      new ApiError("nothing_changed", "The words are the same as before.", 400),
    );

    store.correctTranscript("analysis-1", [{ segmentId: "seg-1", text: "same" }]);
    await settle();

    expect(store.getSnapshot().correction).toEqual({
      status: "failed",
      analysisId: "analysis-1",
      message: "The words are the same as before.",
    });
    expect(store.getSnapshot().viewed).toMatchObject({ analysis: { analysisId: "analysis-1" } });
  });

  it("does not send a second correction while one is being saved", async () => {
    const { store, api } = await withOpenAnalysis();
    api.correctTranscript.mockReturnValue(new Promise(() => {}));

    store.correctTranscript("analysis-1", [{ segmentId: "seg-1", text: "one" }]);
    store.correctTranscript("analysis-1", [{ segmentId: "seg-1", text: "two" }]);

    expect(api.correctTranscript).toHaveBeenCalledTimes(1);
  });

  it("plays the same recording for a revision, and frees it only when neither needs it", async () => {
    const { store, api, tick, revoked } = setup();
    store.submit(submission);
    await settle();
    api.getJob.mockResolvedValue(job({ status: "succeeded", analysisId: "analysis-1" }));
    await tick();
    api.correctTranscript.mockResolvedValue(revision("analysis-2", 2));

    store.correctTranscript("analysis-1", [{ segmentId: "seg-1", text: "words" }]);
    await settle();
    expect(store.getSnapshot().localAudio).toEqual({
      "analysis-1": "blob:take-1",
      "analysis-2": "blob:take-1",
    });

    store.deleteAnalysis("analysis-1");
    await settle();
    expect(revoked).toEqual([]); // the revision still plays it
    expect(store.getSnapshot().localAudio).toEqual({ "analysis-2": "blob:take-1" });

    store.deleteAnalysis("analysis-2");
    await settle();
    expect(revoked).toEqual(["blob:take-1"]);
  });

  it("follows a fresh analysis of a kept recording and shows the new revision", async () => {
    const { store, api, tick, run } = await withOpenAnalysis();
    const again = (overrides: Partial<JobStatus> = {}) =>
      job({ jobId: "job-r", sourceAnalysisId: "analysis-1", ...overrides });
    api.requestReanalysis.mockResolvedValue(again());

    expect(store.reanalyse("analysis-1")).toBe(true);
    expect(store.getSnapshot()).toMatchObject({
      runKind: "analysis",
      reanalysisFor: "analysis-1",
      coachingFor: null,
    });
    await settle();

    expect(api.requestReanalysis).toHaveBeenCalledWith("analysis-1");
    expect(api.submitAnalysis).not.toHaveBeenCalled(); // the kept recording is used
    expect(run()).toMatchObject({ phase: "tracking", job: { jobId: "job-r" } });

    api.getJob.mockResolvedValue(again({ status: "succeeded", analysisId: "analysis-2" }));
    api.getAnalysis.mockResolvedValue(revision("analysis-2", 2));
    await tick();

    expect(run()).toMatchObject({ phase: "done", analysisId: "analysis-2" });
    expect(store.getSnapshot().viewed).toMatchObject({ analysis: { analysisId: "analysis-2" } });
  });

  it("measures the original again, and the watched monologue follows the new revision", async () => {
    const { store, api, tick } = setup();
    api.listMonologues.mockResolvedValue({ items: [monologue("m1", "ref-1")] });
    api.getAnalysis.mockImplementation((id: string) => Promise.resolve(referenceResult(id)));
    store.init();
    store.watchMonologue("m1");
    await settle();
    const again = (overrides: Partial<JobStatus> = {}) =>
      job({ jobId: "job-r", role: "reference", sourceAnalysisId: "ref-1", ...overrides });
    api.requestReanalysis.mockResolvedValue(again());

    expect(store.reanalyse("ref-1", "reference")).toBe(true);
    expect(store.getSnapshot()).toMatchObject({ runRole: "reference", reanalysisFor: "ref-1" });
    await settle();

    api.getJob.mockResolvedValue(again({ status: "succeeded", analysisId: "ref-2" }));
    api.listMonologues.mockResolvedValue({ items: [monologue("m1", "ref-2")] });
    await tick();
    await settle();

    // The monologue is the same one; its takes are now compared with the new revision.
    expect(store.getSnapshot().selectedReferenceId).toBe("ref-2");
    expect(store.getSnapshot().monologues.items).toEqual([monologue("m1", "ref-2")]);
    expect(store.getSnapshot().viewed).toEqual({ status: "none" });
  });

  it("says why when the recording cannot be analysed again", async () => {
    const { store, api, run } = await withOpenAnalysis();
    api.requestReanalysis.mockRejectedValue(
      new ApiError("audio_not_kept", "The recording was not kept.", 409),
    );

    store.reanalyse("analysis-1");
    await settle();

    expect(run()).toMatchObject({
      phase: "failed",
      job: null,
      error: { code: "audio_not_kept" },
      canResubmit: false,
    });
  });

  it("does not start a fresh analysis while another run is in progress", async () => {
    const { store, api } = await withOpenAnalysis();
    store.submit(submission);
    await settle();

    expect(store.reanalyse("analysis-1")).toBe(false);
    expect(api.requestReanalysis).not.toHaveBeenCalled();
  });

  it("recognises a fresh analysis picked up again after a page refresh", async () => {
    const { store, api } = setup({ [ACTIVE_JOB_KEY]: "job-r" });
    api.getJob.mockResolvedValue(
      job({ jobId: "job-r", status: "running", sourceAnalysisId: "analysis-1" }),
    );

    store.init();
    await settle();

    expect(store.getSnapshot().reanalysisFor).toBe("analysis-1");
  });

  it("forgets the earlier recording once an ordinary upload starts", async () => {
    const { store, api } = await withOpenAnalysis();
    api.requestReanalysis.mockRejectedValue(new ApiError("audio_not_kept", "Not kept.", 409));
    store.reanalyse("analysis-1");
    await settle();

    store.submit(submission);

    expect(store.getSnapshot().reanalysisFor).toBeNull();
  });
});

/**
 * A backend holding the given monologues. A recording whose ID starts with "ref" is an
 * original; one written "m1:take-1" is a take of monologue m1; anything else is a take
 * that belongs to no monologue.
 */
function withMonologues(items: Monologue[], stored: Record<string, string> = {}) {
  const context = setup(stored);
  const { api } = context;
  api.listMonologues.mockResolvedValue({ items });
  api.getAnalysis.mockImplementation((id: string) =>
    Promise.resolve(
      id.startsWith("ref") ? referenceResult(id) : id.includes(":") ? takeOf(id) : analysis(id),
    ),
  );
  api.getComparison.mockImplementation((takeId: string, referenceId: string) =>
    Promise.resolve(comparison(takeId, referenceId)),
  );
  /** Gives each monologue the takes listed for it, and the history the rest. */
  const takes = (byMonologue: Record<string, string[]>) =>
    api.listAnalyses.mockImplementation((_limit: number, _role?: string, scope?: string) => {
      const ids = byMonologue[scope ?? ""] ?? [];
      return Promise.resolve({ items: ids.map((id) => summary(id)), total: ids.length });
    });
  return { ...context, takes };
}

describe("monologues", () => {
  it("are loaded when the screen opens, and none is watched until a screen says so", async () => {
    const { store, api } = withMonologues([monologue("m1", "ref-1"), monologue("m2", "ref-2")]);
    store.init();
    await settle();

    expect(api.listMonologues).toHaveBeenCalledTimes(1);
    const state = store.getSnapshot();
    expect(state.monologues).toMatchObject({ status: "ready" });
    expect(state.monologues.items.map((item) => item.monologueId)).toEqual(["m1", "m2"]);
    expect(state.monologueId).toBeNull();
    expect(state.selectedReferenceId).toBeNull();
    expect(state.takes).toMatchObject({ monologueId: null, items: [] });
  });

  it("reports a list that could not be loaded", async () => {
    const { store, api } = setup();
    api.listMonologues.mockRejectedValue(new ApiError("unreachable", "No backend.", 0));
    store.init();
    await settle();
    expect(store.getSnapshot().monologues).toMatchObject({ status: "error", message: "No backend." });
  });

  it("watching one loads its takes and chooses its original for study", async () => {
    const { store, api, takes } = withMonologues([monologue("m1", "ref-1")]);
    takes({ m1: ["m1:take-2", "m1:take-1"], [NO_MONOLOGUE]: ["free"] });
    store.init();
    await settle();

    store.watchMonologue("m1");
    expect(store.getSnapshot().takes).toMatchObject({ monologueId: "m1", status: "loading" });
    // The list is already here, so the original is chosen at once.
    expect(store.getSnapshot().selectedReferenceId).toBe("ref-1");
    expect(store.getSnapshot().referenceDetail).toEqual({ status: "loading", analysisId: "ref-1" });
    await settle();

    expect(api.listAnalyses).toHaveBeenCalledWith(TAKES_LIMIT, "take", "m1");
    const state = store.getSnapshot();
    expect(state.takes).toMatchObject({ monologueId: "m1", status: "ready", total: 2 });
    expect(state.takes.items.map((item) => item.analysisId)).toEqual(["m1:take-2", "m1:take-1"]);
    expect(state.referenceDetail).toMatchObject({ status: "ready", analysis: { analysisId: "ref-1" } });
    // The General Practice history holds only the takes that belong to no monologue.
    expect(state.history.items.map((item) => item.analysisId)).toEqual(["free"]);
  });

  it("chooses the original once the list arrives, if a monologue was watched before it had", async () => {
    const { store } = withMonologues([monologue("m1", "ref-1")]);
    store.init();
    store.watchMonologue("m1");
    expect(store.getSnapshot().selectedReferenceId).toBeNull();

    await settle();
    expect(store.getSnapshot().selectedReferenceId).toBe("ref-1");
  });

  it("chooses nothing for a monologue that does not exist", async () => {
    const { store } = withMonologues([monologue("m1", "ref-1")]);
    store.init();
    await settle();

    store.watchMonologue("gone");
    await settle();
    expect(store.getSnapshot().selectedReferenceId).toBeNull();
    expect(store.getSnapshot().referenceDetail).toEqual({ status: "none" });
  });

  it("moving to another monologue brings its original and takes, not a late answer for the first", async () => {
    const { store, api } = withMonologues([monologue("m1", "ref-1"), monologue("m2", "ref-2")]);
    store.init();
    await settle();
    let answer: (value: AnalysisList) => void = () => {};
    api.listAnalyses.mockImplementation((_limit: number, _role?: string, scope?: string) =>
      scope === "m1"
        ? new Promise<AnalysisList>((resolve) => (answer = resolve))
        : Promise.resolve({ items: scope === "m2" ? [summary("m2:take-1")] : [], total: 1 }),
    );

    store.watchMonologue("m1");
    store.watchMonologue("m2");
    await settle();
    answer({ items: [summary("m1:take-1")], total: 1 }); // the slow first answer arrives last
    await settle();

    const state = store.getSnapshot();
    expect(state.selectedReferenceId).toBe("ref-2");
    expect(state.takes.monologueId).toBe("m2");
    expect(state.takes.items.map((item) => item.analysisId)).toEqual(["m2:take-1"]);
  });

  it("watching none lets go of the original and the takes", async () => {
    const { store, takes } = withMonologues([monologue("m1", "ref-1")]);
    takes({ m1: ["m1:take-1"] });
    store.init();
    store.watchMonologue("m1");
    await settle();

    store.watchMonologue(null);

    const state = store.getSnapshot();
    expect(state.monologueId).toBeNull();
    expect(state.selectedReferenceId).toBeNull();
    expect(state.referenceDetail).toEqual({ status: "none" });
    expect(state.takes).toMatchObject({ monologueId: null, items: [] });
  });

  it("an earlier revision of the original stays open until the original itself changes", async () => {
    const { store, api } = withMonologues([monologue("m1", "ref-2")]);
    store.init();
    store.watchMonologue("m1");
    await settle();

    store.selectReference("ref-1"); // the user opens the earlier revision
    store.refreshMonologues(); // the list is fetched again and says nothing new
    await settle();
    expect(store.getSnapshot().selectedReferenceId).toBe("ref-1");

    api.listMonologues.mockResolvedValue({ items: [monologue("m1", "ref-3")] });
    store.refreshMonologues();
    await settle();
    expect(store.getSnapshot().selectedReferenceId).toBe("ref-3");
  });

  it("sends a take with its monologue, shows it, and brings every list up to date", async () => {
    const { store, api, tick, takes } = withMonologues([monologue("m1", "ref-1")]);
    store.init();
    store.watchMonologue("m1");
    await settle();

    store.submit({ ...submission, monologueId: "m1" });
    await settle();
    expect(api.submitAnalysis).toHaveBeenCalledWith(expect.objectContaining({ monologueId: "m1" }));

    takes({ m1: ["m1:take-1"] });
    api.listMonologues.mockResolvedValue({ items: [monologue("m1", "ref-1", 1)] });
    api.getJob.mockResolvedValue(
      job({ status: "succeeded", analysisId: "m1:take-1", monologueId: "m1" }),
    );
    await tick();
    await settle();

    const state = store.getSnapshot();
    expect(state.viewed).toMatchObject({ status: "ready", analysis: { analysisId: "m1:take-1" } });
    expect(state.takes.items.map((item) => item.analysisId)).toEqual(["m1:take-1"]);
    expect(state.monologues.items[0].takeCount).toBe(1);
    // It is not in the General Practice history, and is at once set against the original.
    expect(state.history.items).toEqual([]);
    expect(state.comparison).toMatchObject({
      status: "ready",
      takeId: "m1:take-1",
      referenceId: "ref-1",
    });
  });

  it("adds a monologue without disturbing the take on view", async () => {
    const { store, api, tick } = withMonologues([]);
    store.init();
    store.openAnalysis("take-1");
    await settle();

    api.submitAnalysis.mockResolvedValue(job({ role: "reference" }));
    store.submit({ ...submission, role: "reference", title: "The original", previewUrl: "blob:ref" });
    expect(store.getSnapshot().runRole).toBe("reference");
    await settle();
    expect(api.submitAnalysis).toHaveBeenCalledWith(
      expect.objectContaining({ role: "reference", title: "The original" }),
    );

    api.listMonologues.mockResolvedValue({ items: [monologue("ref-new", "ref-new")] });
    api.getJob.mockResolvedValue(job({ role: "reference", status: "succeeded", analysisId: "ref-new" }));
    await tick();
    await settle();

    const state = store.getSnapshot();
    expect(state.run).toMatchObject({ phase: "done", analysisId: "ref-new" });
    // The take stays on view; the new monologue is listed and its original can be played.
    expect(state.viewed).toMatchObject({ status: "ready", analysis: { analysisId: "take-1" } });
    expect(state.monologues.items.map((item) => item.monologueId)).toEqual(["ref-new"]);
    expect(state.localAudio).toEqual({ "ref-new": "blob:ref" });
    // Nothing is watched on the screen that adds one, so nothing is chosen or compared.
    expect(state.selectedReferenceId).toBeNull();
    expect(state.comparison).toEqual({ status: "none" });
  });

  it("deletes a monologue with its takes, and stops showing any of it", async () => {
    const { store, api, takes } = withMonologues([monologue("m1", "ref-1"), monologue("m2", "ref-2")]);
    takes({ m1: ["m1:take-1", "m1:take-2"] });
    store.init();
    store.watchMonologue("m1");
    store.openAnalysis("m1:take-1");
    await settle();
    expect(store.getSnapshot().comparison.status).toBe("ready");

    api.deleteMonologue.mockResolvedValue({ deletedReferences: 1, deletedTakes: 2 });
    api.listMonologues.mockResolvedValue({ items: [monologue("m2", "ref-2")] });
    store.deleteMonologue("m1");
    await settle();

    expect(api.deleteMonologue).toHaveBeenCalledWith("m1");
    const state = store.getSnapshot();
    expect(state.monologues.items.map((item) => item.monologueId)).toEqual(["m2"]);
    expect(state.viewed).toEqual({ status: "none" });
    expect(state.takes.items).toEqual([]);
    expect(state.selectedReferenceId).toBeNull();
    expect(state.comparison).toEqual({ status: "none" });
    expect(state.notice).toEqual({ kind: "info", text: "Monologue deleted, with its 2 takes." });
  });

  it("deleting a monologue that is not on view leaves what is on view alone", async () => {
    const { store, api } = withMonologues([monologue("m1", "ref-1"), monologue("m2", "ref-2")]);
    store.init();
    store.watchMonologue("m1");
    store.openAnalysis("m1:take-1");
    await settle();

    api.listMonologues.mockResolvedValue({ items: [monologue("m1", "ref-1")] });
    store.deleteMonologue("m2");
    await settle();

    const state = store.getSnapshot();
    expect(state.viewed).toMatchObject({ status: "ready", analysis: { analysisId: "m1:take-1" } });
    expect(state.selectedReferenceId).toBe("ref-1");
    expect(state.notice).toEqual({ kind: "info", text: "Monologue deleted." });
  });

  it("says why a monologue could not be deleted, and keeps it", async () => {
    const { store, api } = withMonologues([monologue("m1", "ref-1")]);
    store.init();
    await settle();
    api.deleteMonologue.mockRejectedValue(
      new ApiError("monologue_busy", "A recording of this monologue is still being analysed.", 409),
    );

    store.deleteMonologue("m1");
    await settle();

    expect(store.getSnapshot().monologues.items).toHaveLength(1);
    expect(store.getSnapshot().notice).toEqual({
      kind: "error",
      text: "A recording of this monologue is still being analysed.",
    });
  });

  it("deleting a take removes it from its monologue's takes", async () => {
    const { store, takes } = withMonologues([monologue("m1", "ref-1", 2)]);
    takes({ m1: ["m1:take-2", "m1:take-1"] });
    store.init();
    store.watchMonologue("m1");
    store.openAnalysis("m1:take-2");
    await settle();

    takes({ m1: ["m1:take-1"] });
    store.deleteAnalysis("m1:take-2");
    await settle();

    const state = store.getSnapshot();
    expect(state.takes.items.map((item) => item.analysisId)).toEqual(["m1:take-1"]);
    expect(state.takes.total).toBe(1);
    expect(state.viewed).toEqual({ status: "none" });
    expect(state.comparison).toEqual({ status: "none" });
  });

  it("deleting the original's recording says the monologue can no longer be played", async () => {
    const { store } = withMonologues([monologue("m1", "ref-1")]);
    store.init();
    store.watchMonologue("m1");
    await settle();

    store.deleteAudio("ref-1");
    await settle();

    const state = store.getSnapshot();
    expect(state.monologues.items[0].audioRetained).toBe(false);
    expect(state.referenceDetail).toMatchObject({ analysis: { audioRetained: false } });
  });

  it("clearing the General Practice history leaves a monologue's take, its run and its recording", async () => {
    const { store, api, tick, run, revoked } = withMonologues([monologue("m1", "ref-1")]);
    store.init();
    store.watchMonologue("m1");
    await settle();
    store.submit({ ...submission, monologueId: "m1" });
    await settle();
    api.getJob.mockResolvedValue(
      job({ status: "succeeded", analysisId: "m1:take-1", monologueId: "m1" }),
    );
    await tick();
    await settle();

    api.clearAnalyses.mockResolvedValue({ deletedAnalyses: 3, deletedJobs: 3 });
    store.clearHistory();
    await settle();

    // Only the takes that belong to no monologue were asked to go.
    expect(api.clearAnalyses).toHaveBeenCalledWith(NO_MONOLOGUE);
    const state = store.getSnapshot();
    expect(state.viewed).toMatchObject({ status: "ready", analysis: { analysisId: "m1:take-1" } });
    expect(run()).toMatchObject({ phase: "done", analysisId: "m1:take-1" });
    expect(state.localAudio).toEqual({ "m1:take-1": "blob:take-1" });
    expect(revoked).toEqual([]);
    expect(state.selectedReferenceId).toBe("ref-1");
  });
});

describe("comparing a take with its monologue's original", () => {
  async function ready() {
    const context = withMonologues([monologue("m1", "ref-1"), monologue("m2", "ref-2")]);
    context.store.init();
    await settle();
    return context;
  }

  it("is fetched as soon as a take of the watched monologue is on view", async () => {
    const { store, api } = await ready();
    store.watchMonologue("m1");
    await settle();
    expect(store.getSnapshot().comparison).toEqual({ status: "none" });
    expect(api.getComparison).not.toHaveBeenCalled();

    store.openAnalysis("m1:take-1");
    await settle();
    expect(api.getComparison).toHaveBeenCalledWith("m1:take-1", "ref-1");
    expect(store.getSnapshot().comparison).toMatchObject({
      status: "ready",
      data: { takeId: "m1:take-1", referenceId: "ref-1" },
    });
  });

  it("is not made for a take that belongs to no monologue", async () => {
    const { store, api } = await ready();
    store.watchMonologue("m1");
    store.openAnalysis("free-take");
    await settle();

    expect(api.getComparison).not.toHaveBeenCalled();
    expect(store.getSnapshot().comparison).toEqual({ status: "none" });
  });

  it("is never made with the original of a monologue the take was not recorded for", async () => {
    const { store, api } = await ready();
    store.watchMonologue("m1");
    store.openAnalysis("m2:take-1");
    await settle();
    expect(api.getComparison).not.toHaveBeenCalled();

    // Once the screen is about the take's own monologue, it is compared with that one's.
    store.watchMonologue("m2");
    await settle();
    expect(api.getComparison).toHaveBeenCalledTimes(1);
    expect(api.getComparison).toHaveBeenCalledWith("m2:take-1", "ref-2");
  });

  it("follows a change of take or of revision, and is not fetched twice for the same pair", async () => {
    const { store, api } = await ready();
    store.watchMonologue("m1");
    store.openAnalysis("m1:take-1");
    await settle();
    expect(api.getComparison).toHaveBeenCalledTimes(1);

    store.selectReference("ref-0"); // an earlier revision of the original
    await settle();
    expect(store.getSnapshot().comparison).toMatchObject({ status: "ready", referenceId: "ref-0" });

    store.openAnalysis("m1:take-2");
    await settle();
    expect(store.getSnapshot().comparison).toMatchObject({ status: "ready", takeId: "m1:take-2" });
    expect(api.getComparison).toHaveBeenCalledTimes(3);

    // The same pair again, e.g. after new coaching replaced the take on view.
    store.selectReference("ref-0");
    await settle();
    expect(api.getComparison).toHaveBeenCalledTimes(3);
  });

  it("goes away when the take is closed or no monologue is watched", async () => {
    const { store } = await ready();
    store.watchMonologue("m1");
    store.openAnalysis("m1:take-1");
    await settle();

    store.closeAnalysis();
    expect(store.getSnapshot().comparison).toEqual({ status: "none" });

    store.openAnalysis("m1:take-1");
    await settle();
    expect(store.getSnapshot().comparison.status).toBe("ready");
    store.watchMonologue(null);
    expect(store.getSnapshot().comparison).toEqual({ status: "none" });
  });

  it("is never made between an original and itself", async () => {
    const { store, api } = await ready();
    store.watchMonologue("m1");
    store.openAnalysis("ref-1"); // the original opened as if it were a result
    await settle();
    expect(api.getComparison).not.toHaveBeenCalled();
    expect(store.getSnapshot().comparison).toEqual({ status: "none" });
  });

  it("says why when the comparison could not be made", async () => {
    const { store, api } = await ready();
    api.getComparison.mockRejectedValue(new ApiError("reference_not_found", "No such reference.", 404));
    store.watchMonologue("m1");
    store.openAnalysis("m1:take-1");
    await settle();
    expect(store.getSnapshot().comparison).toEqual({
      status: "error",
      takeId: "m1:take-1",
      referenceId: "ref-1",
      message: "No such reference.",
    });
  });

  it("ignores an answer for a pair that is no longer wanted", async () => {
    const { store, api } = await ready();
    let answer: (value: Comparison) => void = () => {};
    api.getComparison.mockImplementationOnce(
      () => new Promise<Comparison>((resolve) => (answer = resolve)),
    );
    store.watchMonologue("m1");
    store.openAnalysis("m1:take-1");
    await settle();

    store.selectReference("ref-0");
    await settle();
    answer(comparison("m1:take-1", "ref-1")); // the slow first answer arrives last
    await settle();
    expect(store.getSnapshot().comparison).toMatchObject({ status: "ready", referenceId: "ref-0" });
  });
});

describe("waveform outlines", () => {
  const outline = { durationSeconds: 2, secondsPerPoint: 1, minimum: [-0.1, -0.2], maximum: [0.1, 0.2] };

  it("are fetched only when asked for, and only once", async () => {
    const { store, api } = setup();
    api.getWaveform.mockResolvedValue(outline);
    expect(store.getSnapshot().waveforms).toEqual({});

    store.loadWaveform("take-1");
    expect(store.getSnapshot().waveforms).toEqual({ "take-1": { status: "loading" } });
    store.loadWaveform("take-1");
    await settle();

    expect(api.getWaveform).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().waveforms["take-1"]).toEqual({ status: "ready", data: outline });
  });

  it("tell a recording analysed before waveforms existed from a real failure", async () => {
    const { store, api } = setup();
    api.getWaveform.mockRejectedValueOnce(new ApiError("waveform_not_stored", "None stored.", 404));
    store.loadWaveform("old");
    api.getWaveform.mockRejectedValueOnce(new ApiError("unreachable", "No backend.", 0));
    store.loadWaveform("new");
    await settle();

    expect(store.getSnapshot().waveforms).toEqual({
      old: { status: "missing" },
      new: { status: "error", message: "No backend." },
    });
  });

  it("does not change the analysis on view, the run or the comparison", async () => {
    const { store, api } = setup();
    api.getWaveform.mockResolvedValue(outline);
    store.openAnalysis("analysis-1");
    await settle();
    const before = store.getSnapshot();

    store.loadWaveform("analysis-1");
    await settle();

    const after = store.getSnapshot();
    expect(after.viewed).toBe(before.viewed);
    expect(after.run).toBe(before.run);
    expect(after.comparison).toBe(before.comparison);
    expect(api.submitAnalysis).not.toHaveBeenCalled();
  });
});
