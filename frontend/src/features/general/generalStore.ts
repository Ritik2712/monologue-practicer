/**
 * The state of the General Practice screen, and everything that changes it: submitting a
 * recording, following its job, showing a result, and managing the history.
 *
 * Like the checklist's store it knows nothing about React. The backend client, the timer
 * and the browser storage are passed in, so tests can script the backend and move time.
 */
import { ApiError, describeError, type GeneralApi } from "./api";
import type {
  AnalysisOptions,
  AnalysisResult,
  AnalysisSummary,
  JobStatus,
  LanguageHint,
  Profile,
} from "./types";

/** Remembers a job that is still in progress, so a page refresh can pick it up again. */
export const ACTIVE_JOB_KEY = "monologue-coach.general.active-job";

/** How often a job in progress is checked. Slow enough not to hammer the backend. */
export const POLL_MS = 1000;
/** When the backend stops answering, checks back off up to this long. */
export const MAX_POLL_MS = 5000;
export const HISTORY_LIMIT = 20;

export type ErrorInfo = { code: string; message: string };

export type Submission = {
  audio: Blob;
  filename: string;
  profile: Profile;
  language: LanguageHint;
  retainAudio: boolean;
  /** An object URL for the same audio, so the result can be played back in this session. */
  previewUrl: string | null;
};

export type RunState =
  | { phase: "idle" }
  | { phase: "submitting" }
  /** `contact` is "lost" while the backend is not answering status checks. */
  | { phase: "tracking"; job: JobStatus; contact: "ok" | "lost" }
  | { phase: "loading_result"; job: JobStatus }
  | { phase: "done"; job: JobStatus; analysisId: string }
  | { phase: "cancelled"; job: JobStatus }
  /**
   * `job` is null when the upload itself was refused or never arrived. `canResubmit`
   * means sending the very same recording again could work (the backend was unreachable).
   */
  | { phase: "failed"; job: JobStatus | null; error: ErrorInfo; canResubmit: boolean };

export type ViewedState =
  | { status: "none" }
  | { status: "loading"; analysisId: string }
  | { status: "ready"; analysis: AnalysisResult }
  | { status: "error"; analysisId: string; message: string };

export type GeneralState = {
  options:
    | { status: "loading" }
    | { status: "ready"; data: AnalysisOptions }
    | { status: "error"; message: string };
  history: {
    status: "loading" | "ready" | "error";
    items: AnalysisSummary[];
    total: number;
    message: string | null;
  };
  run: RunState;
  viewed: ViewedState;
  notice: { kind: "info" | "error"; text: string } | null;
  /** Recordings held in this page's memory, by analysis ID. Gone after a refresh. */
  localAudio: Record<string, string>;
};

export type GeneralStore = {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => GeneralState;
  /** Loads options and history, and resumes a job left in progress. Safe to call twice. */
  init: () => void;
  loadOptions: () => void;
  refreshHistory: () => void;
  /** Returns false, doing nothing, if an analysis is already in progress. */
  submit: (submission: Submission) => boolean;
  /** Sends the last recording again after the backend could not be reached. */
  resubmit: () => void;
  cancel: () => void;
  retry: () => void;
  /** Clears a finished, failed or cancelled run so a new one can start. */
  dismissRun: () => void;
  openAnalysis: (analysisId: string) => void;
  closeAnalysis: () => void;
  deleteAnalysis: (analysisId: string) => void;
  deleteAudio: (analysisId: string) => void;
  clearHistory: () => void;
  dismissNotice: () => void;
};

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

type StoreDeps = {
  api: GeneralApi;
  /** Runs `callback` after `ms`; returns a function that cancels it. */
  schedule: (callback: () => void, ms: number) => () => void;
  /** A fresh idempotency key. */
  newKey: () => string;
  getStorage: () => StorageLike | null;
  /** Releases an object URL once its recording is no longer needed. */
  revokeUrl?: (url: string) => void;
};

const INITIAL: GeneralState = {
  options: { status: "loading" },
  history: { status: "loading", items: [], total: 0, message: null },
  run: { phase: "idle" },
  viewed: { status: "none" },
  notice: null,
  localAudio: {},
};

export const INITIAL_GENERAL_STATE = INITIAL;

export function createGeneralStore({
  api,
  schedule,
  newKey,
  getStorage,
  revokeUrl = () => {},
}: StoreDeps): GeneralStore {
  const listeners = new Set<() => void>();
  let state = INITIAL;
  let initialised = false;
  let pending: { submission: Submission; key: string } | null = null;
  let cancelPoll: (() => void) | null = null;
  let failedPolls = 0;
  /** Goes up whenever the run is replaced, so answers to old requests are ignored. */
  let runToken = 0;

  function set(patch: Partial<GeneralState>) {
    state = { ...state, ...patch };
    listeners.forEach((listener) => listener());
  }

  function remember(jobId: string | null) {
    try {
      const storage = getStorage();
      if (jobId) storage?.setItem(ACTIVE_JOB_KEY, jobId);
      else storage?.removeItem(ACTIVE_JOB_KEY);
    } catch {
      // Storage is a convenience here; the run itself does not depend on it.
    }
  }

  function stopPolling() {
    cancelPoll?.();
    cancelPoll = null;
    failedPolls = 0;
  }

  function startRun(): number {
    stopPolling();
    runToken += 1;
    return runToken;
  }

  function pollLater(jobId: string, token: number) {
    cancelPoll?.();
    const delay = Math.min(MAX_POLL_MS, POLL_MS * 2 ** failedPolls);
    cancelPoll = schedule(() => {
      cancelPoll = null;
      void poll(jobId, token);
    }, delay);
  }

  async function poll(jobId: string, token: number) {
    try {
      const job = await api.getJob(jobId);
      if (token !== runToken) return;
      failedPolls = 0;
      await handleJob(job, token);
    } catch (error) {
      if (token !== runToken) return;
      if (error instanceof ApiError && error.status === 404) {
        remember(null);
        set({
          run: {
            phase: "failed",
            job: null,
            error: { code: "job_not_found", message: "This analysis no longer exists." },
            canResubmit: false,
          },
        });
        return;
      }
      // The backend is briefly away: keep the last known status, say so, and keep trying.
      failedPolls += 1;
      if (state.run.phase === "tracking") set({ run: { ...state.run, contact: "lost" } });
      pollLater(jobId, token);
    }
  }

  async function handleJob(job: JobStatus, token: number) {
    switch (job.status) {
      case "queued":
      case "running":
        remember(job.jobId);
        set({ run: { phase: "tracking", job, contact: "ok" } });
        pollLater(job.jobId, token);
        return;
      case "cancelled":
        remember(null);
        set({ run: { phase: "cancelled", job } });
        return;
      case "failed":
        // Kept in storage: a retryable failure can still be retried after a refresh.
        remember(job.jobId);
        set({
          run: {
            phase: "failed",
            job,
            error: job.error ?? { code: "unknown", message: "The analysis failed." },
            canResubmit: false,
          },
        });
        return;
      case "succeeded":
        await loadResult(job, token);
        return;
    }
  }

  async function loadResult(job: JobStatus, token: number) {
    const analysisId = job.analysisId;
    if (!analysisId) return;
    set({ run: { phase: "loading_result", job } });
    try {
      const analysis = await api.getAnalysis(analysisId);
      if (token !== runToken) return;
      remember(null);
      const previewUrl = pending?.submission.previewUrl;
      pending = null;
      set({
        run: { phase: "done", job, analysisId },
        viewed: { status: "ready", analysis },
        localAudio: previewUrl ? { ...state.localAudio, [analysisId]: previewUrl } : state.localAudio,
      });
      refreshHistory();
    } catch (error) {
      if (token !== runToken) return;
      set({
        run: { phase: "failed", job, error: describeError(error), canResubmit: false },
      });
    }
  }

  async function send(token: number) {
    if (!pending) return;
    const { submission, key } = pending;
    set({ run: { phase: "submitting" }, notice: null });
    try {
      const job = await api.submitAnalysis({
        audio: submission.audio,
        filename: submission.filename,
        profile: submission.profile,
        language: submission.language,
        retainAudio: submission.retainAudio,
        idempotencyKey: key,
      });
      if (token !== runToken) return;
      await handleJob(job, token);
    } catch (error) {
      if (token !== runToken) return;
      const info = describeError(error);
      set({
        run: {
          phase: "failed",
          job: null,
          error: info,
          // A refusal (wrong type, too big) will be refused again. Only an upload that
          // never got an answer is worth sending again, with the same key.
          canResubmit: info.status === 0 || info.status >= 500,
        },
      });
    }
  }

  function loadOptions() {
    set({ options: { status: "loading" } });
    api.getOptions().then(
      (data) => set({ options: { status: "ready", data } }),
      (error) => set({ options: { status: "error", message: describeError(error).message } }),
    );
  }

  function refreshHistory() {
    api.listAnalyses(HISTORY_LIMIT).then(
      ({ items, total }) => set({ history: { status: "ready", items, total, message: null } }),
      (error) =>
        set({
          history: { ...state.history, status: "error", message: describeError(error).message },
        }),
    );
  }

  function forget(analysisIds: string[]) {
    const localAudio = { ...state.localAudio };
    for (const id of analysisIds) {
      if (localAudio[id]) revokeUrl(localAudio[id]);
      delete localAudio[id];
    }
    return localAudio;
  }

  function isBusy() {
    return ["submitting", "tracking", "loading_result"].includes(state.run.phase);
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot: () => state,

    init() {
      if (initialised) return;
      initialised = true;
      loadOptions();
      refreshHistory();
      let jobId: string | null = null;
      try {
        jobId = getStorage()?.getItem(ACTIVE_JOB_KEY) ?? null;
      } catch {
        jobId = null;
      }
      if (jobId) void poll(jobId, startRun());
    },
    loadOptions,
    refreshHistory,

    submit(submission) {
      if (isBusy()) return false;
      pending = { submission, key: newKey() };
      void send(startRun());
      return true;
    },

    resubmit() {
      if (state.run.phase !== "failed" || !state.run.canResubmit || !pending) return;
      // Same key as before: if the first attempt did reach the backend, this returns
      // that job instead of creating a second one.
      void send(startRun());
    },

    cancel() {
      const { run } = state;
      if (run.phase !== "tracking" && !(run.phase === "failed" && run.job)) return;
      const job = run.job as JobStatus;
      const token = runToken;
      api.cancelJob(job.jobId).then(
        (updated) => {
          if (token !== runToken) return;
          if (updated.status === "failed") {
            // Discarding a failed job: its kept audio is gone, so there is nothing to retry.
            remember(null);
            pending = null;
            set({ run: { phase: "idle" } });
            return;
          }
          void handleJob(updated, token);
        },
        (error) => set({ notice: { kind: "error", text: describeError(error).message } }),
      );
    },

    retry() {
      const { run } = state;
      if (run.phase !== "failed" || !run.job?.canRetry) return;
      const token = startRun();
      api.retryJob(run.job.jobId).then(
        (job) => {
          if (token === runToken) void handleJob(job, token);
        },
        (error) => {
          if (token !== runToken) return;
          set({ notice: { kind: "error", text: describeError(error).message } });
        },
      );
    },

    dismissRun() {
      if (isBusy()) return;
      startRun();
      remember(null);
      pending = null;
      set({ run: { phase: "idle" } });
    },

    openAnalysis(analysisId) {
      set({ viewed: { status: "loading", analysisId } });
      api.getAnalysis(analysisId).then(
        (analysis) => {
          const { viewed } = state;
          if (viewed.status === "loading" && viewed.analysisId === analysisId) {
            set({ viewed: { status: "ready", analysis } });
          }
        },
        (error) => {
          const { viewed } = state;
          if (viewed.status === "loading" && viewed.analysisId === analysisId) {
            set({
              viewed: { status: "error", analysisId, message: describeError(error).message },
            });
          }
        },
      );
    },

    closeAnalysis() {
      set({ viewed: { status: "none" } });
    },

    deleteAnalysis(analysisId) {
      api.deleteAnalysis(analysisId).then(
        () => {
          const { viewed, run } = state;
          const showing = viewed.status === "ready" && viewed.analysis.analysisId === analysisId;
          const justRan = run.phase === "done" && run.analysisId === analysisId;
          set({
            history: {
              ...state.history,
              items: state.history.items.filter((item) => item.analysisId !== analysisId),
              total: Math.max(0, state.history.total - 1),
            },
            viewed: showing ? { status: "none" } : viewed,
            run: justRan ? { phase: "idle" } : run,
            localAudio: forget([analysisId]),
            notice: { kind: "info", text: "Analysis deleted." },
          });
          refreshHistory();
        },
        (error) => set({ notice: { kind: "error", text: describeError(error).message } }),
      );
    },

    deleteAudio(analysisId) {
      api.deleteAnalysisAudio(analysisId).then(
        () => {
          const { viewed } = state;
          set({
            history: {
              ...state.history,
              items: state.history.items.map((item) =>
                item.analysisId === analysisId ? { ...item, audioRetained: false } : item,
              ),
            },
            viewed:
              viewed.status === "ready" && viewed.analysis.analysisId === analysisId
                ? { status: "ready", analysis: { ...viewed.analysis, audioRetained: false } }
                : viewed,
            // The user asked for the recording to go, so the copy in memory goes too.
            localAudio: forget([analysisId]),
            notice: { kind: "info", text: "Recording deleted. The measurements were kept." },
          });
        },
        (error) => set({ notice: { kind: "error", text: describeError(error).message } }),
      );
    },

    clearHistory() {
      api.clearAnalyses().then(
        ({ deletedAnalyses }) => {
          const finished = !isBusy();
          if (finished) {
            startRun();
            remember(null);
            pending = null;
          }
          set({
            history: { status: "ready", items: [], total: 0, message: null },
            viewed: { status: "none" },
            run: finished ? { phase: "idle" } : state.run,
            localAudio: forget(Object.keys(state.localAudio)),
            notice: {
              kind: "info",
              text:
                deletedAnalyses === 1
                  ? "History cleared: 1 analysis deleted."
                  : `History cleared: ${deletedAnalyses} analyses deleted.`,
            },
          });
        },
        (error) => set({ notice: { kind: "error", text: describeError(error).message } }),
      );
    },

    dismissNotice() {
      set({ notice: null });
    },
  };
}
