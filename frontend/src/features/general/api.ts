/**
 * Every request the General Practice screen makes to the local backend. Nothing else in
 * the feature calls `fetch`, so tests can replace this one object.
 */
import { apiUrl } from "@/lib/api";

import type {
  AnalysisList,
  AnalysisOptions,
  AnalysisResult,
  Calibration,
  Comparison,
  FeedbackRequest,
  FeedbackSummary,
  FeedbackUpdate,
  Health,
  JobStatus,
  LanguageHint,
  MonologueList,
  Profile,
  Role,
  SegmentCorrection,
  Waveform,
} from "./types";

/** A failed request, in the backend's own {code, message} terms. */
export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    /** The HTTP status, or 0 when the backend could not be reached at all. */
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type SubmitRequest = {
  audio: Blob;
  filename: string;
  profile: Profile;
  language: LanguageHint;
  retainAudio: boolean;
  /** A take (the default) or a reference recording to compare takes against. */
  role?: Role;
  /** The name a reference is listed under. */
  title?: string;
  /** The monologue a take is recorded for. Left out for a take that belongs to none. */
  monologueId?: string;
  /** Sent as the Idempotency-Key header: the same key never creates a second job. */
  idempotencyKey: string;
};

export type GeneralApi = {
  getHealth: () => Promise<Health>;
  getOptions: () => Promise<AnalysisOptions>;
  submitAnalysis: (request: SubmitRequest) => Promise<JobStatus>;
  getJob: (jobId: string) => Promise<JobStatus>;
  cancelJob: (jobId: string) => Promise<JobStatus>;
  retryJob: (jobId: string) => Promise<JobStatus>;
  getAnalysis: (analysisId: string) => Promise<AnalysisResult>;
  /** Asks for an analysis's coaching to be written again. Returns a job to follow. */
  requestCoaching: (analysisId: string) => Promise<JobStatus>;
  /**
   * Past takes, or the reference recordings when `role` is "reference". `monologue` narrows
   * the takes to one monologue's, or with NO_MONOLOGUE to those that belong to none.
   */
  listAnalyses: (limit: number, role?: Role, monologue?: string) => Promise<AnalysisList>;
  /** The monologues being practised, the one practised most recently first. */
  listMonologues: () => Promise<MonologueList>;
  /** Deletes a monologue: its reference recording in every revision, and all its takes. */
  deleteMonologue: (
    monologueId: string,
  ) => Promise<{ deletedReferences: number; deletedTakes: number }>;
  /** A take set against a reference recording. */
  getComparison: (analysisId: string, referenceId: string) => Promise<Comparison>;
  /** The outline of a recording's sound wave, for drawing. */
  getWaveform: (analysisId: string) => Promise<Waveform>;
  deleteAnalysis: (analysisId: string) => Promise<void>;
  deleteAnalysisAudio: (analysisId: string) => Promise<void>;
  /** Clears the takes, narrowed by `monologue` as `listAnalyses` is. */
  clearAnalyses: (monologue?: string) => Promise<{ deletedAnalyses: number; deletedJobs: number }>;
  /** Address of a kept recording, for an <audio> element. */
  analysisAudioUrl: (analysisId: string) => string;
  /** The feedback given on an analysis, and the calibration as it stands. */
  getFeedback: (analysisId: string) => Promise<FeedbackUpdate>;
  giveFeedback: (analysisId: string, feedback: FeedbackRequest) => Promise<FeedbackUpdate>;
  deleteFeedback: (feedbackId: string) => Promise<FeedbackUpdate>;
  getCalibration: () => Promise<Calibration>;
  undoCalibration: () => Promise<Calibration>;
  resetCalibration: () => Promise<Calibration>;
  setAdaptive: (enabled: boolean) => Promise<Calibration>;
  /** Stores a new revision with corrected words. Returns that revision. */
  correctTranscript: (
    analysisId: string,
    corrections: SegmentCorrection[],
  ) => Promise<AnalysisResult>;
  /** Asks for the kept recording to be analysed again. Returns a job to follow. */
  requestReanalysis: (analysisId: string) => Promise<JobStatus>;
  /** What all the stored feedback adds up to, your notes, and the AI model's pick if any. */
  getFeedbackSummary: () => Promise<FeedbackSummary>;
  /** Asks the AI model to pick the most telling notes. The answer carries the job to follow. */
  requestFeedbackSummary: () => Promise<FeedbackSummary>;
};

/** Asks for the takes that belong to no monologue: the ones made in General Practice. */
export const NO_MONOLOGUE = "none";

export const UNREACHABLE_MESSAGE =
  "The local backend could not be reached. Make sure the API is running, then try again.";

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export function createApi(fetchImpl: FetchLike = (input, init) => fetch(input, init)): GeneralApi {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetchImpl(apiUrl(path), init);
    } catch {
      throw new ApiError("unreachable", UNREACHABLE_MESSAGE, 0);
    }
    if (response.ok) {
      return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
    }
    throw await toApiError(response);
  }

  const post = (path: string) => request<JobStatus>(path, { method: "POST" });
  const sendJson = <T>(path: string, method: string, body: unknown) =>
    request<T>(path, {
      method,
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    });

  return {
    getHealth: () => request("/api/health"),
    getOptions: () => request("/api/analysis-options"),
    submitAnalysis: ({
      audio,
      filename,
      profile,
      language,
      retainAudio,
      role,
      title,
      monologueId,
      idempotencyKey,
    }) => {
      const form = new FormData();
      form.append("audio", audio, filename);
      form.append("profile", profile);
      form.append("language", language);
      form.append("retainAudio", String(retainAudio));
      if (role) form.append("role", role);
      if (title) form.append("title", title);
      if (monologueId) form.append("monologueId", monologueId);
      return request("/api/analyses", {
        method: "POST",
        body: form,
        headers: { "Idempotency-Key": idempotencyKey },
      });
    },
    getJob: (jobId) => request(`/api/jobs/${encodeURIComponent(jobId)}`),
    cancelJob: (jobId) => post(`/api/jobs/${encodeURIComponent(jobId)}/cancel`),
    retryJob: (jobId) => post(`/api/jobs/${encodeURIComponent(jobId)}/retry`),
    getAnalysis: (analysisId) => request(`/api/analyses/${encodeURIComponent(analysisId)}`),
    requestCoaching: (analysisId) =>
      post(`/api/analyses/${encodeURIComponent(analysisId)}/coaching`),
    listAnalyses: (limit, role, monologue) =>
      request(
        `/api/analyses?limit=${limit}${role ? `&role=${role}` : ""}${
          monologue ? `&monologue=${encodeURIComponent(monologue)}` : ""
        }`,
      ),
    listMonologues: () => request("/api/monologues"),
    deleteMonologue: (monologueId) =>
      request(`/api/monologues/${encodeURIComponent(monologueId)}`, { method: "DELETE" }),
    getComparison: (analysisId, referenceId) =>
      request(
        `/api/analyses/${encodeURIComponent(analysisId)}/comparison/${encodeURIComponent(referenceId)}`,
      ),
    getWaveform: (analysisId) =>
      request(`/api/analyses/${encodeURIComponent(analysisId)}/waveform`),
    deleteAnalysis: (analysisId) =>
      request(`/api/analyses/${encodeURIComponent(analysisId)}`, { method: "DELETE" }),
    deleteAnalysisAudio: (analysisId) =>
      request(`/api/analyses/${encodeURIComponent(analysisId)}/audio`, { method: "DELETE" }),
    clearAnalyses: (monologue) =>
      request(`/api/analyses${monologue ? `?monologue=${encodeURIComponent(monologue)}` : ""}`, {
        method: "DELETE",
      }),
    analysisAudioUrl: (analysisId) =>
      apiUrl(`/api/analyses/${encodeURIComponent(analysisId)}/audio`),
    getFeedback: (analysisId) =>
      request(`/api/analyses/${encodeURIComponent(analysisId)}/feedback`),
    giveFeedback: (analysisId, feedback) =>
      sendJson(`/api/analyses/${encodeURIComponent(analysisId)}/feedback`, "POST", feedback),
    deleteFeedback: (feedbackId) =>
      request(`/api/feedback/${encodeURIComponent(feedbackId)}`, { method: "DELETE" }),
    getCalibration: () => request("/api/calibration"),
    undoCalibration: () => request("/api/calibration/undo", { method: "POST" }),
    resetCalibration: () => request("/api/calibration/reset", { method: "POST" }),
    setAdaptive: (enabled) => sendJson("/api/calibration/adaptive", "PUT", { enabled }),
    correctTranscript: (analysisId, corrections) =>
      sendJson(`/api/analyses/${encodeURIComponent(analysisId)}/transcript`, "POST", {
        corrections,
      }),
    requestReanalysis: (analysisId) =>
      post(`/api/analyses/${encodeURIComponent(analysisId)}/reanalysis`),
    getFeedbackSummary: () => request("/api/feedback-summary"),
    requestFeedbackSummary: () => request("/api/feedback-summary", { method: "POST" }),
  };
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { detail?: { code?: unknown; message?: unknown } };
    const { code, message } = body.detail ?? {};
    if (typeof code === "string" && typeof message === "string") {
      return new ApiError(code, message, response.status);
    }
  } catch {
    // Not JSON: fall through to the generic message.
  }
  return new ApiError(
    "unexpected_response",
    `The backend answered with an error (${response.status}).`,
    response.status,
  );
}

export function describeError(error: unknown): { code: string; message: string; status: number } {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.message, status: error.status };
  }
  return { code: "unexpected", message: "Something went wrong in the page.", status: -1 };
}
