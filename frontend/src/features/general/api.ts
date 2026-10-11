/**
 * Every request the General Practice screen makes to the local backend. Nothing else in
 * the feature calls `fetch`, so tests can replace this one object.
 */
import { apiUrl } from "@/lib/api";

import type {
  AnalysisList,
  AnalysisOptions,
  AnalysisResult,
  Health,
  JobStatus,
  LanguageHint,
  Profile,
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
  listAnalyses: (limit: number) => Promise<AnalysisList>;
  deleteAnalysis: (analysisId: string) => Promise<void>;
  deleteAnalysisAudio: (analysisId: string) => Promise<void>;
  clearAnalyses: () => Promise<{ deletedAnalyses: number; deletedJobs: number }>;
  /** Address of a kept recording, for an <audio> element. */
  analysisAudioUrl: (analysisId: string) => string;
};

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

  return {
    getHealth: () => request("/api/health"),
    getOptions: () => request("/api/analysis-options"),
    submitAnalysis: ({ audio, filename, profile, language, retainAudio, idempotencyKey }) => {
      const form = new FormData();
      form.append("audio", audio, filename);
      form.append("profile", profile);
      form.append("language", language);
      form.append("retainAudio", String(retainAudio));
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
    listAnalyses: (limit) => request(`/api/analyses?limit=${limit}`),
    deleteAnalysis: (analysisId) =>
      request(`/api/analyses/${encodeURIComponent(analysisId)}`, { method: "DELETE" }),
    deleteAnalysisAudio: (analysisId) =>
      request(`/api/analyses/${encodeURIComponent(analysisId)}/audio`, { method: "DELETE" }),
    clearAnalyses: () => request("/api/analyses", { method: "DELETE" }),
    analysisAudioUrl: (analysisId) =>
      apiUrl(`/api/analyses/${encodeURIComponent(analysisId)}/audio`),
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
