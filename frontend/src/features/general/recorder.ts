/**
 * Recording from the microphone with the browser's MediaRecorder.
 *
 * The browser pieces it needs are passed in as `RecorderEnv`, so tests can stand in for a
 * microphone. Whatever happens — stop, discard, an error — the microphone is released, so
 * the browser's "recording" indicator never stays on by accident.
 */

export type RecorderErrorCode =
  | "unsupported"
  | "insecure_context"
  | "permission_denied"
  | "no_microphone"
  | "microphone_busy"
  | "empty"
  | "failed";

export type Recording = {
  blob: Blob;
  /** An address the page can play the recording from, or null where that is not possible. */
  url: string | null;
  durationMs: number;
  mimeType: string;
  /** File extension matching the format the browser recorded in, e.g. ".webm". */
  extension: string;
  /** True when recording was stopped automatically at the length limit. */
  reachedLimit: boolean;
};

export type RecorderState =
  | { status: "idle" }
  /** Waiting for the user to answer the browser's microphone prompt. */
  | { status: "requesting" }
  | { status: "recording"; elapsedMs: number }
  | { status: "recorded"; recording: Recording }
  | { status: "error"; code: RecorderErrorCode; message: string };

type TrackLike = { stop: () => void };
type StreamLike = { getTracks: () => TrackLike[] };
type RecorderLike = {
  mimeType: string;
  start: (timesliceMs?: number) => void;
  stop: () => void;
  ondataavailable: ((event: { data: Blob }) => void) | null;
  onstop: (() => void) | null;
  onerror: ((event: unknown) => void) | null;
};
export type RecorderCtor = {
  new (stream: StreamLike, options?: { mimeType?: string }): RecorderLike;
  isTypeSupported?: (mimeType: string) => boolean;
};

export type RecorderEnv = {
  getUserMedia: ((constraints: { audio: true }) => Promise<StreamLike>) | null;
  MediaRecorder: RecorderCtor | null;
  isSecureContext: boolean;
  /** Makes a playable address for a recording (URL.createObjectURL in a browser). */
  createUrl?: (blob: Blob) => string;
  now: () => number;
  setInterval: (callback: () => void, ms: number) => unknown;
  clearInterval: (handle: unknown) => void;
};

export type Recorder = {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => RecorderState;
  start: (maxMs: number) => void;
  stop: () => void;
  /** Throws away the current recording, or abandons one in progress. */
  discard: () => void;
};

/** Formats to ask for, best first. Browsers differ: Chrome and Firefox do WebM, Safari MP4. */
const PREFERRED_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

const MESSAGES: Record<RecorderErrorCode, string> = {
  unsupported: "This browser cannot record audio here. You can upload a file instead.",
  insecure_context:
    "Recording only works on a secure page. Open the app at http://localhost, or upload a file instead.",
  permission_denied:
    "Microphone access was blocked. Allow the microphone for this site in the browser's address bar, then try again.",
  no_microphone: "No microphone was found. Connect one, or upload a file instead.",
  microphone_busy:
    "The microphone could not be started. Another app may be using it. Close that app and try again.",
  empty: "No audio was captured. Check that the microphone is working, then record again.",
  failed: "Recording stopped unexpectedly. Please try again.",
};

const ELAPSED_TICK_MS = 250;
/** Asks the browser to hand over audio every second, so a crash loses little. */
const TIMESLICE_MS = 1000;

export function extensionFor(mimeType: string): string {
  const type = mimeType.toLowerCase();
  if (type.includes("mp4") || type.includes("aac")) return ".m4a";
  if (type.includes("ogg")) return ".ogg";
  if (type.includes("wav")) return ".wav";
  return ".webm";
}

function errorCodeFor(error: unknown): RecorderErrorCode {
  const name = typeof error === "object" && error !== null ? (error as { name?: string }).name : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "permission_denied";
    case "NotFoundError":
    case "OverconstrainedError":
      return "no_microphone";
    case "NotReadableError":
    case "AbortError":
      return "microphone_busy";
    default:
      return "failed";
  }
}

export function createRecorder(env: RecorderEnv): Recorder {
  const listeners = new Set<() => void>();
  let state: RecorderState = { status: "idle" };
  /** Goes up on every start or discard, so a late answer from an old attempt is ignored. */
  let attempt = 0;
  let stream: StreamLike | null = null;
  let recorder: RecorderLike | null = null;
  let ticker: unknown = null;

  function set(next: RecorderState) {
    state = next;
    listeners.forEach((listener) => listener());
  }

  function fail(code: RecorderErrorCode) {
    set({ status: "error", code, message: MESSAGES[code] });
  }

  function release() {
    if (ticker !== null) env.clearInterval(ticker);
    ticker = null;
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    recorder = null;
  }

  async function begin(maxMs: number, current: number) {
    const Ctor = env.MediaRecorder;
    if (!env.isSecureContext) return fail("insecure_context");
    if (!env.getUserMedia || !Ctor) return fail("unsupported");

    set({ status: "requesting" });
    let granted: StreamLike;
    try {
      granted = await env.getUserMedia({ audio: true });
    } catch (error) {
      if (current === attempt) fail(errorCodeFor(error));
      return;
    }
    if (current !== attempt) {
      // Discarded while the permission prompt was open: let go of the microphone at once.
      granted.getTracks().forEach((track) => track.stop());
      return;
    }

    stream = granted;
    const chunks: Blob[] = [];
    let reachedLimit = false;
    const mimeType = PREFERRED_TYPES.find((type) => Ctor.isTypeSupported?.(type));
    try {
      recorder = new Ctor(granted, mimeType ? { mimeType } : undefined);
    } catch {
      release();
      return fail("unsupported");
    }

    const startedAt = env.now();
    const active = recorder;
    active.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    active.onerror = () => {
      if (current !== attempt) return;
      release();
      fail("failed");
    };
    active.onstop = () => {
      if (current !== attempt) return;
      const durationMs = env.now() - startedAt;
      const type = active.mimeType || mimeType || "audio/webm";
      release();
      const blob = new Blob(chunks, { type });
      // Never report success with nothing in hand.
      if (blob.size === 0) return fail("empty");
      set({
        status: "recorded",
        recording: {
          blob,
          url: env.createUrl?.(blob) ?? null,
          durationMs,
          mimeType: type,
          extension: extensionFor(type),
          reachedLimit,
        },
      });
    };

    try {
      active.start(TIMESLICE_MS);
    } catch {
      release();
      return fail("microphone_busy");
    }
    set({ status: "recording", elapsedMs: 0 });
    ticker = env.setInterval(() => {
      if (current !== attempt || state.status !== "recording") return;
      // Elapsed time comes from the clock, not from counting ticks.
      const elapsedMs = env.now() - startedAt;
      if (elapsedMs >= maxMs) {
        reachedLimit = true;
        active.stop();
        return;
      }
      set({ status: "recording", elapsedMs });
    }, ELAPSED_TICK_MS);
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot: () => state,

    start(maxMs) {
      if (state.status === "requesting" || state.status === "recording") return;
      attempt += 1;
      void begin(maxMs, attempt);
    },

    stop() {
      if (state.status === "recording") recorder?.stop();
    },

    discard() {
      attempt += 1;
      const active = recorder;
      release();
      try {
        active?.stop();
      } catch {
        // Already stopped.
      }
      set({ status: "idle" });
    },
  };
}

/** The real browser, or stand-ins that report "unsupported" where there is no browser. */
export function browserRecorderEnv(): RecorderEnv {
  const hasWindow = typeof window !== "undefined";
  const devices = hasWindow ? navigator.mediaDevices : undefined;
  return {
    getUserMedia: devices?.getUserMedia ? (constraints) => devices.getUserMedia(constraints) : null,
    MediaRecorder:
      hasWindow && typeof window.MediaRecorder !== "undefined"
        ? (window.MediaRecorder as unknown as RecorderCtor)
        : null,
    isSecureContext: hasWindow ? window.isSecureContext : false,
    createUrl: (blob) => URL.createObjectURL(blob),
    now: () => performance.now(),
    setInterval: (callback, ms) => window.setInterval(callback, ms),
    clearInterval: (handle) => window.clearInterval(handle as number),
  };
}
