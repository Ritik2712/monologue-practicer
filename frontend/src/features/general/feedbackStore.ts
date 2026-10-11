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
  FeedbackUpdate,
} from "./types";

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
};

export function createFeedbackStore(api: GeneralApi): FeedbackStore {
  const listeners = new Set<() => void>();
  let state = INITIAL_FEEDBACK_STATE;
  let inFlight = 0;

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
      return;
    }
    set({ status: "ready", items: update.items, message: null, calibration, adjustments });
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

    dismissAdjustments() {
      set({ adjustments: [] });
    },
    dismissError() {
      set({ error: null });
    },
  };
}
