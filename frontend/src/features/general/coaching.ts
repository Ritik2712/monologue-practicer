/**
 * Small decisions about how coaching is shown. Kept apart from the components so they can
 * be tested without rendering anything.
 */
import type { GeneralState } from "./generalStore";
import type { CoachStatus, Coaching, Evidence, Finding, SpeechSegment } from "./types";

/** Seconds of audio played either side of a pause, so the pause is heard in context. */
export const PAUSE_CONTEXT_SECONDS = 1.5;

/** The stretch of the recording to play for a piece of evidence. Null if there is none. */
export function playRange(evidence: Evidence): { start: number; end: number } | null {
  if (evidence.startSeconds === null || evidence.endSeconds === null) return null;
  if (evidence.kind === "pause") {
    return {
      start: Math.max(0, evidence.startSeconds - PAUSE_CONTEXT_SECONDS),
      end: evidence.endSeconds + PAUSE_CONTEXT_SECONDS,
    };
  }
  return { start: evidence.startSeconds, end: evidence.endSeconds };
}

export function findingById(coaching: Coaching, findingId: string): Finding | undefined {
  return coaching.findings.find((finding) => finding.id === findingId);
}

/** The words of the phrase a correction is practised on, straight from the transcript. */
export function practiseLine(evidence: Evidence | null, segments: SpeechSegment[]): string | null {
  if (!evidence || evidence.kind !== "segment") return null;
  return segments.find((segment) => segment.id === evidence.id)?.transcript ?? null;
}

/** What to do about a reason the AI model could not be used. Null when nothing can be done. */
export function coachHelp(code: string, model: string | null): { text: string; command?: string } | null {
  switch (code) {
    case "not_running":
      return { text: "Open the Ollama app, or start it in a terminal:", command: "ollama serve" };
    case "model_missing":
      return {
        text: "This app never downloads a model for you. To install it yourself (several gigabytes):",
        command: `ollama pull ${model ?? "llama3.1:8b"}`,
      };
    case "not_local":
      return {
        text: "In the .env file, set OLLAMA_BASE_URL to an address on this computer, such as http://localhost:11434, and restart the worker.",
      };
    case "off":
    case "ai_off":
      return { text: "To switch it on, set AI_COACHING=on in the .env file and restart the worker." };
    case "timeout":
      return {
        text: "The first answer after Ollama starts is the slowest, so trying again often works. The limit can be raised with OLLAMA_TIMEOUT_SECONDS in the .env file.",
      };
    default:
      return null;
  }
}

/** In a few words, why AI coaching is not available right now. */
export const COACH_STATUS_TEXT: Record<Exclude<CoachStatus, "ready" | "unknown">, string> = {
  not_running: "Ollama is not running",
  model_missing: "the AI model is not installed in Ollama",
  not_local: "OLLAMA_BASE_URL does not point at this computer",
  off: "it is switched off in the settings",
};

/**
 * Whether asking the AI model for coaching again could change anything.
 *
 * Not when there was nothing to coach on, and not when nothing measured needs correcting:
 * the model would be given the same empty list.
 */
export function canRegenerate(coaching: Coaching | null): boolean {
  if (coaching === null) return true;
  if (coaching.source === "none") return false;
  return coaching.notice?.code !== "nothing_to_correct";
}

/**
 * How the latest request to write one analysis's coaching again is going, for showing next
 * to the button that started it.
 */
export function regenerationState(
  state: Pick<GeneralState, "run" | "runKind" | "coachingFor">,
  analysisId: string,
):
  | { status: "idle" }
  | { status: "running" }
  | { status: "done" }
  | { status: "failed"; message: string } {
  const { run } = state;
  if (state.runKind !== "coaching" || state.coachingFor !== analysisId) return { status: "idle" };
  switch (run.phase) {
    case "submitting":
    case "tracking":
    case "loading_result":
      return { status: "running" };
    case "done":
      return { status: "done" };
    case "failed":
      return { status: "failed", message: run.error.message };
    default:
      return { status: "idle" };
  }
}

/**
 * Where a recording can be played from: the copy held in this page's memory if there is
 * one, else the copy the backend kept, else nowhere.
 */
export function audioSourceFor(
  recording: { analysisId: string; audioRetained: boolean },
  localAudio: Record<string, string>,
  api: { analysisAudioUrl: (analysisId: string) => string },
): string | null {
  return (
    localAudio[recording.analysisId] ??
    (recording.audioRetained ? api.analysisAudioUrl(recording.analysisId) : null)
  );
}
