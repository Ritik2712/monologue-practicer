/**
 * The feedback given on the result on view, and the calibration it feeds.
 *
 * Kept apart from the store that runs analyses: feedback is saved with one small request
 * and never has a job to follow. Like the other stores it knows nothing about React.
 */
import { describeError, type GeneralApi } from "./api";
import type {
  Calibration,
  CalibrationChange,
  FeedbackItem,
  FeedbackRequest,
  FeedbackSummary,
  FeedbackUpdate,
} from "./types";

/** How often a request to the AI model is asked after while the worker has it. */
export const SUMMARY_POLL_MS = 2000;

/** Runs `callback` after `ms`; returns a function that cancels it. */
export type Schedule = (callback: () => void, ms: number) => () => void;

const defaultSchedule: Schedule = (callback, ms) => {
  const handle = setTimeout(callback, ms);
  return () => clearTimeout(handle);
};

export type SummaryState =
  | { status: "idle" }
  | { status: "loading" }
  | {
      status: "ready";
      data: FeedbackSummary;
      /** True from the click on "ask the AI model" until the backend has answered it. */
      asking: boolean;
      /** Why the request to the AI model, or to stop it, was refused. */
      error: string | null;
    }
  | { status: "error"; message: string };

export type FeedbackState = {
  /** The analysis whose feedback is shown. Null when no result is on view. */
  analysisId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  /** Every piece of feedback on that analysis, oldest first. */
  items: FeedbackItem[];
  /** Why the feedback could not be loaded. */
  message: string | null;
  /** True while feedback is being saved or taken back. */
  saving: boolean;
  /** Why the latest save, or the latest change to the calibration, failed. */
  error: string | null;
  calibration:
    | { status: "loading" }
    | { status: "ready"; data: Calibration }
    | { status: "error"; message: string };
  /** Settings that feedback has just moved, until the user dismisses the notice. */
  adjustments: CalibrationChange[];
  /** What all the stored feedback adds up to. Belongs to the whole app, like the calibration. */
  summary: SummaryState;
};

export type FeedbackStore = {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => FeedbackState;
  /** Shows the feedback of this analysis from now on. Null shows none. */
  watch: (analysisId: string | null) => void;
  /** Saves one piece of feedback on the analysis being watched. */
  give: (feedback: FeedbackRequest) => void;
  /** Takes one piece of feedback back. */
  remove: (feedbackId: string) => void;
  loadCalibration: () => void;
  undo: () => void;
  reset: () => void;
  setAdaptive: (enabled: boolean) => void;
  loadSummary: () => void;
  /** Asks the AI model to pick out the most telling notes. */
  askForSummary: () => void;
  /** Stops that request while it is waiting or being answered. */
  cancelSummary: () => void;
  dismissAdjustments: () => void;
  dismissError: () => void;
};

export const INITIAL_FEEDBACK_STATE: FeedbackState = {
  analysisId: null,
  status: "idle",
  items: [],
  message: null,
  saving: false,
  error: null,
  calibration: { status: "loading" },
  adjustments: [],
  summary: { status: "idle" },
};

export function createFeedbackStore(
  api: GeneralApi,
  schedule: Schedule = defaultSchedule,
): FeedbackStore {
  const listeners = new Set<() => void>();
  let state = INITIAL_FEEDBACK_STATE;
  let inFlight = 0;
  let cancelSummaryPoll: (() => void) | null = null;
  /** Goes up with every request for the summary, so a late answer cannot replace a newer one. */
  let summaryToken = 0;

  function set(patch: Partial<FeedbackState>) {
    state = { ...state, ...patch };
    listeners.forEach((listener) => listener());
  }

  /** Takes in the backend's answer, unless the user has moved on to another result. */
  function accept(analysisId: string, update: FeedbackUpdate) {
    const calibration = { status: "ready" as const, data: update.calibration };
    const adjustments = [...state.adjustments, ...update.adjustments];
    if (state.analysisId !== analysisId) {
      // The calibration belongs to the whole app, so it is still worth keeping.
      set({ calibration, adjustments });
    } else {
      set({ status: "ready", items: update.items, message: null, calibration, adjustments });
    }
    refreshSummary();
  }

  function showSummary(data: FeedbackSummary, error: string | null = null) {
    cancelSummaryPoll?.();
    cancelSummaryPoll = null;
    set({ summary: { status: "ready", data, asking: false, error } });
    // While the worker has it, ask again shortly: there is no other way to hear it is done.
    if (data.job && (data.job.status === "queued" || data.job.status === "running")) {
      cancelSummaryPoll = schedule(() => {
        cancelSummaryPoll = null;
        loadSummary();
      }, SUMMARY_POLL_MS);
    }
  }

  function loadSummary() {
    summaryToken += 1;
    const token = summaryToken;
    if (state.summary.status !== "ready") set({ summary: { status: "loading" } });
    api.getFeedbackSummary().then(
      (data) => {
        if (token === summaryToken) showSummary(data);
      },
      (error) => {
        if (token !== summaryToken) return;
        if (state.summary.status === "ready") {
          // An earlier good answer is worth more than an error in its place. If the AI
          // model was being asked, keep checking: the backend may only be away for a moment.
          const { job } = state.summary.data;
          if (job && (job.status === "queued" || job.status === "running")) {
            cancelSummaryPoll?.();
            cancelSummaryPoll = schedule(() => {
              cancelSummaryPoll = null;
              loadSummary();
            }, SUMMARY_POLL_MS);
          }
          return;
        }
        set({ summary: { status: "error", message: describeError(error).message } });
      },
    );
  }

  /** The facts and the notes come from the feedback, so they change whenever it does. */
  function refreshSummary() {
    if (state.summary.status === "ready") loadSummary();
  }

  /** Sends one request about the summary, then shows what the backend says of it now. */
  function changeSummary(request: (data: FeedbackSummary) => Promise<FeedbackSummary>) {
    const current = state.summary;
    if (current.status !== "ready" || current.asking) return;
    summaryToken += 1;
    const token = summaryToken;
    cancelSummaryPoll?.();
    cancelSummaryPoll = null;
    set({ summary: { ...current, asking: true, error: null } });
    request(current.data).then(
      (data) => {
        if (token === summaryToken) showSummary(data);
      },
      (error) => {
        if (token === summaryToken) showSummary(current.data, describeError(error).message);
      },
    );
  }

  function load(analysisId: string) {
    api.getFeedback(analysisId).then(
      (update) => accept(analysisId, update),
      (error) => {
        if (state.analysisId !== analysisId) return;
        set({ status: "error", message: describeError(error).message });
      },
    );
  }

  function loadCalibration() {
    api.getCalibration().then(
      (data) => set({ calibration: { status: "ready", data } }),
      (error) => {
        // An earlier good answer is worth more than an error in its place.
        if (state.calibration.status === "ready") return;
        set({ calibration: { status: "error", message: describeError(error).message } });
      },
    );
  }

  function started() {
    inFlight += 1;
    set({ saving: true, error: null });
  }

  function finished(error?: unknown) {
    inFlight = Math.max(0, inFlight - 1);
    set({
      saving: inFlight > 0,
      error: error === undefined ? state.error : describeError(error).message,
    });
  }

  /** Runs one change to the calibration, then shows what it led to. */
  function change(request: () => Promise<Calibration>) {
    started();
    request().then(
      (data) => {
        set({ calibration: { status: "ready", data }, adjustments: [] });
        finished();
        // What each piece of feedback "does" is worded against the calibration, so the
        // list on view is fetched again.
        if (state.analysisId) load(state.analysisId);
        else refreshSummary();
      },
      (error) => finished(error),
    );
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot: () => state,

    watch(analysisId) {
      if (analysisId === state.analysisId) return;
      if (analysisId === null) {
        set({ analysisId: null, status: "idle", items: [], message: null, error: null });
        return;
      }
      set({ analysisId, status: "loading", items: [], message: null, error: null });
      load(analysisId);
    },

    give(feedback) {
      const analysisId = state.analysisId;
      if (!analysisId) return;
      started();
      api.giveFeedback(analysisId, feedback).then(
        (update) => {
          accept(analysisId, update);
          finished();
        },
        (error) => finished(error),
      );
    },

    remove(feedbackId) {
      const analysisId = state.analysisId;
      if (!analysisId) return;
      started();
      api.deleteFeedback(feedbackId).then(
        (update) => {
          accept(analysisId, update);
          finished();
        },
        (error) => finished(error),
      );
    },

    loadCalibration,
    undo: () => change(() => api.undoCalibration()),
    reset: () => change(() => api.resetCalibration()),
    setAdaptive: (enabled) => change(() => api.setAdaptive(enabled)),

    loadSummary,
    askForSummary: () => changeSummary(() => api.requestFeedbackSummary()),
    cancelSummary: () =>
      changeSummary((data) =>
        data.job ? api.cancelJob(data.job.jobId).then(() => api.getFeedbackSummary()) : api.getFeedbackSummary(),
      ),

    dismissAdjustments() {
      set({ adjustments: [] });
    },
    dismissError() {
      set({ error: null });
    },
  };
}
