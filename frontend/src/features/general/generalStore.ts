/**
 * The state of the General Practice, Monologues and Daily Practice screens, and everything
 * that changes it: submitting a recording, following its job, showing a result, managing
 * the history, and keeping the monologues, the takes of the one being practised, and the
 * comparison of a take with that monologue's reference recording.
 *
 * Like the checklist's store it knows nothing about React. The backend client, the timer
 * and the browser storage are passed in, so tests can script the backend and move time.
 */
import { ApiError, describeError, NO_MONOLOGUE, type GeneralApi } from "./api";
import type {
  AnalysisOptions,
  AnalysisResult,
  AnalysisSummary,
  Comparison,
  JobKind,
  JobStatus,
  LanguageHint,
  Monologue,
  Profile,
  Role,
  SegmentCorrection,
  Waveform,
} from "./types";

/** Remembers a job that is still in progress, so a page refresh can pick it up again. */
export const ACTIVE_JOB_KEY = "monologue-coach.general.active-job";
/**
 * Written by earlier versions, which remembered a chosen reference between visits. The
 * monologue being practised now says which reference is meant, so the key is cleared.
 */
export const LEGACY_SELECTED_REFERENCE_KEY = "monologue-coach.reference.selected";

/** How often a job in progress is checked. Slow enough not to hammer the backend. */
export const POLL_MS = 1000;
/** When the backend stops answering, checks back off up to this long. */
export const MAX_POLL_MS = 5000;
export const HISTORY_LIMIT = 20;
/** How many of one monologue's takes are listed. */
export const TAKES_LIMIT = 50;

export type ErrorInfo = { code: string; message: string };

export type Submission = {
  audio: Blob;
  filename: string;
  profile: Profile;
  language: LanguageHint;
  retainAudio: boolean;
  /** A take (the default), or a reference recording to compare takes against. */
  role?: Role;
  /** The name a reference is listed under. */
  title?: string;
  /** The monologue a take is recorded for. Left out in General Practice. */
  monologueId?: string;
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

/** A take set against its monologue's reference recording. */
export type ComparisonState =
  | { status: "none" }
  | { status: "loading"; takeId: string; referenceId: string }
  | { status: "ready"; takeId: string; referenceId: string; data: Comparison }
  | { status: "error"; takeId: string; referenceId: string; message: string };

/** The outline of one recording's sound wave, fetched only when it is asked for. */
export type WaveformState =
  | { status: "loading" }
  | { status: "ready"; data: Waveform }
  /** Analysed before waveforms were stored. */
  | { status: "missing" }
  | { status: "error"; message: string };

/** How saving a corrected transcript is going. It is one quick request, with no job. */
export type CorrectionState =
  | { status: "idle" }
  | { status: "saving"; analysisId: string }
  | { status: "failed"; analysisId: string; message: string };

export type GeneralState = {
  options:
    | { status: "loading" }
    | { status: "ready"; data: AnalysisOptions }
    | { status: "error"; message: string };
  /** The General Practice history: the takes that belong to no monologue. */
  history: {
    status: "loading" | "ready" | "error";
    items: AnalysisSummary[];
    total: number;
    message: string | null;
  };
  run: RunState;
  /**
   * What the current run is doing: analysing a recording, or only writing the coaching of
   * an analysis that already exists again.
   */
  runKind: JobKind;
  /** The analysis whose coaching is being written again. Null for an ordinary analysis. */
  coachingFor: string | null;
  /** The analysis whose kept recording is being analysed again. Null otherwise. */
  reanalysisFor: string | null;
  correction: CorrectionState;
  /** Whether the recording in the current run is a take or a reference. */
  runRole: Role;
  viewed: ViewedState;
  /** The monologues being practised, the one practised most recently first. */
  monologues: {
    status: "loading" | "ready" | "error";
    items: Monologue[];
    message: string | null;
  };
  /** The monologue the screen on view is about. Null on a screen that is about none. */
  monologueId: string | null;
  /** That monologue's takes, newest first. */
  takes: {
    monologueId: string | null;
    status: "loading" | "ready" | "error";
    items: AnalysisSummary[];
    total: number;
    message: string | null;
  };
  /**
   * The reference recording on view: the newest revision of the watched monologue's, unless
   * an earlier revision has been opened.
   */
  selectedReferenceId: string | null;
  /** That reference's own full result, for studying it. */
  referenceDetail: ViewedState;
  /**
   * The take on view set against that reference, when the take belongs to the watched
   * monologue. Kept up to date by the store.
   */
  comparison: ComparisonState;
  /** Sound-wave outlines by analysis ID. Only what has been asked for. */
  waveforms: Record<string, WaveformState>;
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
  /**
   * Asks the local AI model to write an analysis's coaching again. The measurements are
   * not touched. Returns false, doing nothing, if something is already in progress.
   */
  regenerateCoaching: (analysisId: string) => boolean;
  /**
   * Analyses an analysis's kept recording again, with the settings in force now. The
   * result is a new revision; the earlier one is not changed. Returns false, doing
   * nothing, if something is already in progress. `role` says whether the recording is one
   * of your takes (the default) or a reference.
   */
  reanalyse: (analysisId: string, role?: Role) => boolean;
  /**
   * Saves the words of some phrases as they were really said. The backend stores a new
   * revision with word counts and WPM worked out again, and that revision is then shown.
   */
  correctTranscript: (analysisId: string, corrections: SegmentCorrection[]) => void;
  /** Clears a finished, failed or cancelled run so a new one can start. */
  dismissRun: () => void;
  openAnalysis: (analysisId: string) => void;
  closeAnalysis: () => void;
  refreshMonologues: () => void;
  /**
   * Says which monologue the screen on view is about. Its takes are loaded and its newest
   * reference recording is chosen. Null when the screen is about no monologue.
   */
  watchMonologue: (monologueId: string | null) => void;
  /** Opens another revision of the watched monologue's reference. Null opens none. */
  selectReference: (analysisId: string | null) => void;
  /** Deletes a monologue: its reference recording in every revision, and all its takes. */
  deleteMonologue: (monologueId: string) => void;
  /** Fetches a recording's sound-wave outline, once. Does nothing if it is already here. */
  loadWaveform: (analysisId: string) => void;
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

const NO_TAKES: GeneralState["takes"] = {
  monologueId: null,
  status: "ready",
  items: [],
  total: 0,
  message: null,
};

const INITIAL: GeneralState = {
  options: { status: "loading" },
  history: { status: "loading", items: [], total: 0, message: null },
  run: { phase: "idle" },
  runKind: "analysis",
  coachingFor: null,
  reanalysisFor: null,
  correction: { status: "idle" },
  runRole: "take",
  viewed: { status: "none" },
  monologues: { status: "loading", items: [], message: null },
  monologueId: null,
  takes: NO_TAKES,
  selectedReferenceId: null,
  referenceDetail: { status: "none" },
  comparison: { status: "none" },
  waveforms: {},
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
  /**
   * The reference last chosen on the watched monologue's behalf. Undefined until one has
   * been: the monologue is then followed again only when its newest reference changes, so
   * an earlier revision the user has opened is not taken away from them.
   */
  let followed: string | null | undefined;
  /**
   * Recordings held in memory that belong to a monologue: its reference, or a take of it.
   * Clearing the General Practice history must not release these.
   */
  const monologueAudio = new Set<string>();

  function apply(patch: Partial<GeneralState>) {
    state = { ...state, ...patch };
    listeners.forEach((listener) => listener());
  }

  function set(patch: Partial<GeneralState>) {
    apply(patch);
    // The reference's details and the comparison follow from what is on view, which
    // monologue is watched and which reference is chosen. They are brought up to date
    // here, in one place, so no action has to remember to do it.
    if ("viewed" in patch || "selectedReferenceId" in patch || "monologueId" in patch) {
      syncWithSelection();
    }
  }

  function syncWithSelection() {
    const referenceId = state.selectedReferenceId;
    const detail = state.referenceDetail;
    const detailId =
      detail.status === "ready"
        ? detail.analysis.analysisId
        : detail.status === "none"
          ? null
          : detail.analysisId;
    if (referenceId === null) {
      if (detail.status !== "none") apply({ referenceDetail: { status: "none" } });
    } else if (detailId !== referenceId) {
      apply({ referenceDetail: { status: "loading", analysisId: referenceId } });
      api.getAnalysis(referenceId).then(
        (analysis) => {
          if (state.selectedReferenceId === referenceId) {
            apply({ referenceDetail: { status: "ready", analysis } });
          }
        },
        (error) => {
          if (state.selectedReferenceId !== referenceId) return;
          apply({
            referenceDetail: {
              status: "error",
              analysisId: referenceId,
              message: describeError(error).message,
            },
          });
        },
      );
    }

    // A take is compared only with the reference of the monologue it was recorded for.
    // A take made in General Practice is compared with none.
    const { viewed, comparison } = state;
    const takeId =
      viewed.status === "ready" &&
      viewed.analysis.role === "take" &&
      !!viewed.analysis.monologueId &&
      viewed.analysis.monologueId === state.monologueId
        ? viewed.analysis.analysisId
        : null;
    if (takeId === null || referenceId === null) {
      if (comparison.status !== "none") apply({ comparison: { status: "none" } });
      return;
    }
    if (
      comparison.status !== "none" &&
      comparison.takeId === takeId &&
      comparison.referenceId === referenceId
    ) {
      return;
    }
    apply({ comparison: { status: "loading", takeId, referenceId } });
    const stillWanted = () =>
      state.comparison.status === "loading" &&
      state.comparison.takeId === takeId &&
      state.comparison.referenceId === referenceId;
    api.getComparison(takeId, referenceId).then(
      (data) => {
        if (stillWanted()) apply({ comparison: { status: "ready", takeId, referenceId, data } });
      },
      (error) => {
        if (!stillWanted()) return;
        apply({
          comparison: {
            status: "error",
            takeId,
            referenceId,
            message: describeError(error).message,
          },
        });
      },
    );
  }

  function selectReference(analysisId: string | null) {
    if (analysisId === state.selectedReferenceId) return;
    set({ selectedReferenceId: analysisId });
  }

  /**
   * Chooses the watched monologue's newest reference: when the monologue is first watched,
   * and again whenever that reference changes (it was corrected, measured again, or the
   * monologue was deleted). In between, the choice is left alone.
   */
  function followMonologue() {
    const monologueId = state.monologueId;
    // Until the list has arrived there is nothing to follow.
    if (monologueId === null || state.monologues.status === "loading") return;
    const watched = state.monologues.items.find((item) => item.monologueId === monologueId);
    const referenceId = watched?.referenceId ?? null;
    if (referenceId === followed) return;
    followed = referenceId;
    selectReference(referenceId);
  }

  function refreshMonologues() {
    api.listMonologues().then(
      ({ items }) => {
        apply({ monologues: { status: "ready", items, message: null } });
        followMonologue();
      },
      (error) =>
        apply({
          monologues: {
            ...state.monologues,
            status: "error",
            message: describeError(error).message,
          },
        }),
    );
  }

  function refreshTakes() {
    const monologueId = state.monologueId;
    if (monologueId === null) return;
    api.listAnalyses(TAKES_LIMIT, "take", monologueId).then(
      ({ items, total }) => {
        // The answer for a monologue that is no longer watched is not wanted.
        if (state.monologueId !== monologueId) return;
        apply({ takes: { monologueId, status: "ready", items, total, message: null } });
      },
      (error) => {
        if (state.monologueId !== monologueId) return;
        apply({
          takes: { ...state.takes, status: "error", message: describeError(error).message },
        });
      },
    );
  }

  /** After a take was added, changed or deleted: every list it could be in. */
  function refreshLists() {
    refreshHistory();
    refreshTakes();
    refreshMonologues();
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
    // A job picked up after a page refresh says for itself what kind it is.
    const reanalysisFor = job.sourceAnalysisId ?? null;
    if (
      state.runKind !== job.kind ||
      state.runRole !== job.role ||
      state.reanalysisFor !== reanalysisFor
    ) {
      set({
        runKind: job.kind,
        runRole: job.role,
        coachingFor: job.kind === "coaching" ? job.analysisId : null,
        reanalysisFor,
      });
    }
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
      const { viewed } = state;
      const localAudio = previewUrl
        ? { ...state.localAudio, [analysisId]: previewUrl }
        : state.localAudio;
      if (job.role === "reference") {
        // A new reference is a new monologue in the list. A reference measured again is a
        // new revision of its monologue: if that monologue is the one being watched, the
        // refreshed list makes the new revision the chosen one. Whatever take is on view
        // stays there.
        monologueAudio.add(analysisId);
        set({ run: { phase: "done", job, analysisId }, localAudio });
        refreshMonologues();
        return;
      }
      if (analysis.monologueId) monologueAudio.add(analysisId);
      // New coaching is shown only if its analysis is still the one on screen: the user
      // may have opened another while the model was writing.
      const show =
        job.kind !== "coaching" ||
        viewed.status === "none" ||
        (viewed.status === "ready" && viewed.analysis.analysisId === analysisId);
      set({
        run: { phase: "done", job, analysisId },
        viewed: show ? { status: "ready", analysis } : viewed,
        localAudio,
      });
      refreshLists();
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
        role: submission.role,
        title: submission.title,
        monologueId: submission.monologueId,
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
    api.listAnalyses(HISTORY_LIMIT, "take", NO_MONOLOGUE).then(
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
      const url = localAudio[id];
      delete localAudio[id];
      // Two revisions of one recording play the same audio: it is released only once
      // neither of them needs it any more.
      if (url && !Object.values(localAudio).includes(url)) revokeUrl(url);
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
        const storage = getStorage();
        jobId = storage?.getItem(ACTIVE_JOB_KEY) ?? null;
        storage?.removeItem(LEGACY_SELECTED_REFERENCE_KEY);
      } catch {
        jobId = null;
      }
      refreshMonologues();
      if (jobId) void poll(jobId, startRun());
    },
    loadOptions,
    refreshHistory,
    refreshMonologues,
    selectReference,

    watchMonologue(monologueId) {
      if (monologueId === state.monologueId) return;
      // If the list is already here this monologue's original is chosen now; otherwise
      // when the list arrives. Either way the choice changes in the same step as the
      // monologue, so a take is never set against the original of the one watched before.
      const listed = monologueId !== null && state.monologues.status !== "loading";
      const referenceId = listed
        ? (state.monologues.items.find((item) => item.monologueId === monologueId)
            ?.referenceId ?? null)
        : null;
      followed = listed ? referenceId : undefined;
      set({
        monologueId,
        takes: monologueId
          ? { monologueId, status: "loading", items: [], total: 0, message: null }
          : NO_TAKES,
        selectedReferenceId: referenceId,
      });
      refreshTakes();
    },

    deleteMonologue(monologueId) {
      api.deleteMonologue(monologueId).then(
        ({ deletedTakes }) => {
          const { viewed, takes, referenceDetail, run } = state;
          const watched = state.monologueId === monologueId;
          // What this page knows it was holding for the monologue.
          const gone = takes.monologueId === monologueId ? takes.items.map((item) => item.analysisId) : [];
          const viewedGone =
            viewed.status === "ready" && viewed.analysis.monologueId === monologueId;
          if (viewedGone) gone.push(viewed.analysis.analysisId);
          if (watched && referenceDetail.status === "ready") {
            gone.push(referenceDetail.analysis.analysisId);
          }
          set({
            monologues: {
              ...state.monologues,
              items: state.monologues.items.filter((item) => item.monologueId !== monologueId),
            },
            takes: watched ? { ...NO_TAKES, monologueId } : takes,
            viewed: viewedGone ? { status: "none" } : viewed,
            run: run.phase === "done" && gone.includes(run.analysisId) ? { phase: "idle" } : run,
            localAudio: forget(gone),
            notice: {
              kind: "info",
              text:
                deletedTakes === 0
                  ? "Monologue deleted."
                  : deletedTakes === 1
                    ? "Monologue deleted, with its 1 take."
                    : `Monologue deleted, with its ${deletedTakes} takes.`,
            },
          });
          followMonologue();
          refreshMonologues();
        },
        (error) => set({ notice: { kind: "error", text: describeError(error).message } }),
      );
    },

    loadWaveform(analysisId) {
      if (state.waveforms[analysisId]) return;
      const store = (waveform: WaveformState) =>
        apply({ waveforms: { ...state.waveforms, [analysisId]: waveform } });
      store({ status: "loading" });
      api.getWaveform(analysisId).then(
        (data) => store({ status: "ready", data }),
        (error) => {
          const info = describeError(error);
          store(
            info.code === "waveform_not_stored"
              ? { status: "missing" }
              : { status: "error", message: info.message },
          );
        },
      );
    },

    submit(submission) {
      if (isBusy()) return false;
      pending = { submission, key: newKey() };
      set({
        runKind: "analysis",
        runRole: submission.role ?? "take",
        coachingFor: null,
        reanalysisFor: null,
      });
      void send(startRun());
      return true;
    },

    reanalyse(analysisId, role = "take") {
      if (isBusy()) return false;
      pending = null;
      const token = startRun();
      set({
        run: { phase: "submitting" },
        runKind: "analysis",
        runRole: role,
        coachingFor: null,
        reanalysisFor: analysisId,
        notice: null,
      });
      api.requestReanalysis(analysisId).then(
        (job) => {
          if (token === runToken) void handleJob(job, token);
        },
        (error) => {
          if (token !== runToken) return;
          set({
            run: { phase: "failed", job: null, error: describeError(error), canResubmit: false },
          });
        },
      );
      return true;
    },

    correctTranscript(analysisId, corrections) {
      if (state.correction.status === "saving") return;
      set({ correction: { status: "saving", analysisId }, notice: null });
      api.correctTranscript(analysisId, corrections).then(
        (revision) => {
          // The same audio plays for the new revision as for the result it came from.
          const url = state.localAudio[analysisId];
          if (revision.role === "reference") {
            // The corrected reference becomes the one its monologue's takes are compared
            // with, so whatever take is on view is now lined up with the corrected words.
            monologueAudio.add(revision.analysisId);
            set({
              correction: { status: "idle" },
              localAudio: url
                ? { ...state.localAudio, [revision.analysisId]: url }
                : state.localAudio,
              notice: {
                kind: "info",
                text: `Saved as revision ${revision.revision} of the original recording. Word counts and WPM were worked out again from the corrected words, and your takes are now compared with this revision. The earlier one is kept, unchanged.`,
              },
            });
            followed = revision.analysisId;
            selectReference(revision.analysisId);
            refreshMonologues();
            return;
          }
          if (revision.monologueId) monologueAudio.add(revision.analysisId);
          const { viewed } = state;
          const stillShown =
            viewed.status === "ready" && viewed.analysis.analysisId === analysisId;
          set({
            correction: { status: "idle" },
            viewed: stillShown ? { status: "ready", analysis: revision } : viewed,
            localAudio: url ? { ...state.localAudio, [revision.analysisId]: url } : state.localAudio,
            notice: {
              kind: "info",
              text: `Saved as revision ${revision.revision}. Word counts and WPM were worked out again from your words. The earlier result is still in your history, unchanged.`,
            },
          });
          refreshLists();
        },
        (error) =>
          set({
            correction: { status: "failed", analysisId, message: describeError(error).message },
          }),
      );
    },

    regenerateCoaching(analysisId) {
      if (isBusy()) return false;
      pending = null;
      const token = startRun();
      set({
        run: { phase: "submitting" },
        runKind: "coaching",
        coachingFor: analysisId,
        reanalysisFor: null,
        notice: null,
      });
      api.requestCoaching(analysisId).then(
        (job) => {
          if (token === runToken) void handleJob(job, token);
        },
        (error) => {
          if (token !== runToken) return;
          set({
            run: { phase: "failed", job: null, error: describeError(error), canResubmit: false },
          });
        },
      );
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
          // The take is in one of the two lists: the history, or its monologue's takes.
          const without = <List extends { items: AnalysisSummary[]; total: number }>(list: List) => {
            const items = list.items.filter((item) => item.analysisId !== analysisId);
            return items.length === list.items.length
              ? list
              : { ...list, items, total: Math.max(0, list.total - 1) };
          };
          set({
            history: without(state.history),
            takes: without(state.takes),
            viewed: showing ? { status: "none" } : viewed,
            run: justRan ? { phase: "idle" } : run,
            localAudio: forget([analysisId]),
            notice: { kind: "info", text: "Analysis deleted." },
          });
          refreshLists();
        },
        (error) => set({ notice: { kind: "error", text: describeError(error).message } }),
      );
    },

    deleteAudio(analysisId) {
      api.deleteAnalysisAudio(analysisId).then(
        () => {
          const { viewed, referenceDetail } = state;
          const withoutAudio = (item: AnalysisSummary) =>
            item.analysisId === analysisId ? { ...item, audioRetained: false } : item;
          const updated = (shown: ViewedState): ViewedState =>
            shown.status === "ready" && shown.analysis.analysisId === analysisId
              ? { status: "ready", analysis: { ...shown.analysis, audioRetained: false } }
              : shown;
          // Applied directly: nothing here changes what is on view or which reference is
          // chosen, so there is nothing to bring up to date.
          apply({
            history: { ...state.history, items: state.history.items.map(withoutAudio) },
            takes: { ...state.takes, items: state.takes.items.map(withoutAudio) },
            monologues: {
              ...state.monologues,
              items: state.monologues.items.map((item) =>
                item.referenceId === analysisId ? { ...item, audioRetained: false } : item,
              ),
            },
            viewed: updated(viewed),
            referenceDetail: updated(referenceDetail),
            // The user asked for the recording to go, so the copy in memory goes too.
            localAudio: forget([analysisId]),
            notice: { kind: "info", text: "Recording deleted. The measurements were kept." },
          });
        },
        (error) => set({ notice: { kind: "error", text: describeError(error).message } }),
      );
    },

    clearHistory() {
      // Only the General Practice history: the takes that belong to no monologue.
      api.clearAnalyses(NO_MONOLOGUE).then(
        ({ deletedAnalyses }) => {
          const { run, viewed } = state;
          // A finished run is cleared with the history, unless it was about a monologue.
          const aboutMonologue =
            state.runRole === "reference" || ("job" in run && !!run.job?.monologueId);
          const finished = !isBusy() && !aboutMonologue;
          if (finished) {
            startRun();
            remember(null);
            pending = null;
          }
          const keepViewed =
            viewed.status === "ready" &&
            (viewed.analysis.role === "reference" || !!viewed.analysis.monologueId);
          set({
            history: { status: "ready", items: [], total: 0, message: null },
            viewed: keepViewed ? viewed : { status: "none" },
            run: finished ? { phase: "idle" } : run,
            localAudio: forget(
              Object.keys(state.localAudio).filter((id) => !monologueAudio.has(id)),
            ),
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
