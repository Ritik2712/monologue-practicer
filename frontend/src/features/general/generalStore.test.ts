import { describe, expect, it, vi } from "vitest";

import { ApiError, type GeneralApi } from "./api";
import {
  ACTIVE_JOB_KEY,
  createGeneralStore,
  MAX_POLL_MS,
  POLL_MS,
  type Submission,
} from "./generalStore";
import type { AnalysisResult, AnalysisSummary, JobStatus } from "./types";

function job(overrides: Partial<JobStatus> = {}): JobStatus {
  return {
    jobId: "job-1",
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

const analysis = (id = "analysis-1") => ({ analysisId: id, audioRetained: false }) as AnalysisResult;
const summary = (id: string, audioRetained = false) =>
  ({ analysisId: id, audioRetained, metrics: {} }) as AnalysisSummary;

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
    listAnalyses: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    deleteAnalysis: vi.fn().mockResolvedValue(undefined),
    deleteAnalysisAudio: vi.fn().mockResolvedValue(undefined),
    clearAnalyses: vi.fn().mockResolvedValue({ deletedAnalyses: 0, deletedJobs: 0 }),
    analysisAudioUrl: (id: string) => `http://api/analyses/${id}/audio`,
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
