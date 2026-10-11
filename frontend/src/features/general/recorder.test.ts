import { describe, expect, it, vi } from "vitest";

import { createRecorder, extensionFor, type RecorderCtor, type RecorderEnv } from "./recorder";

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

/** A stand-in microphone and MediaRecorder that the test drives by hand. */
function setup(options: { supported?: string[]; secure?: boolean; noDevices?: boolean } = {}) {
  let nowMs = 0;
  const tracks = [{ stop: vi.fn() }, { stop: vi.fn() }];
  const stream = { getTracks: () => tracks };
  const getUserMedia = vi.fn().mockResolvedValue(stream);
  const intervals: (() => void)[] = [];
  const created: FakeRecorder[] = [];

  class FakeRecorder {
    static isTypeSupported = (type: string) => (options.supported ?? ["audio/webm"]).includes(type);
    mimeType: string;
    ondataavailable: ((event: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    onerror: ((event: unknown) => void) | null = null;
    started = false;
    stopped = false;
    /** What the "microphone" will have captured by the time recording stops. */
    captured: string[] = ["chunk-a", "chunk-b"];

    constructor(_stream: unknown, recorderOptions?: { mimeType?: string }) {
      this.mimeType = recorderOptions?.mimeType ?? "";
      created.push(this);
    }
    start() {
      this.started = true;
    }
    stop() {
      if (this.stopped) return;
      this.stopped = true;
      for (const text of this.captured) this.ondataavailable?.({ data: new Blob([text]) });
      this.onstop?.();
    }
  }

  const env: RecorderEnv = {
    getUserMedia: options.noDevices ? null : getUserMedia,
    MediaRecorder: options.noDevices ? null : (FakeRecorder as unknown as RecorderCtor),
    isSecureContext: options.secure ?? true,
    createUrl: (blob) => `blob:recording-${blob.size}`,
    now: () => nowMs,
    setInterval: (callback) => intervals.push(callback),
    clearInterval: (handle) => void (intervals[(handle as number) - 1] = () => {}),
  };
  const recorder = createRecorder(env);
  return {
    recorder,
    getUserMedia,
    tracks,
    created,
    state: () => recorder.getSnapshot(),
    /** Moves the clock forward and fires the elapsed-time ticker. */
    advance(ms: number) {
      nowMs += ms;
      intervals.forEach((callback) => callback());
    },
    microphoneReleased: () => tracks.every((track) => track.stop.mock.calls.length === 1),
  };
}

describe("recording", () => {
  it("records, shows elapsed time from the clock, and releases the microphone on stop", async () => {
    const { recorder, state, advance, created, microphoneReleased } = setup();

    recorder.start(60_000);
    expect(state()).toEqual({ status: "requesting" });
    await settle();
    expect(state()).toEqual({ status: "recording", elapsedMs: 0 });
    expect(created[0].started).toBe(true);
    expect(created[0].mimeType).toBe("audio/webm");

    advance(1300);
    advance(4200); // irregular ticks: elapsed is still exact
    expect(state()).toEqual({ status: "recording", elapsedMs: 5500 });

    recorder.stop();
    const final = state();
    expect(final.status).toBe("recorded");
    if (final.status !== "recorded") return;
    expect(final.recording.durationMs).toBe(5500);
    expect(final.recording.blob.size).toBe("chunk-achunk-b".length);
    expect(final.recording.url).toBe("blob:recording-14");
    expect(final.recording.mimeType).toBe("audio/webm");
    expect(final.recording.extension).toBe(".webm");
    expect(final.recording.reachedLimit).toBe(false);
    expect(microphoneReleased()).toBe(true);
  });

  it("uses MP4 where WebM is not available, as in Safari", async () => {
    const { recorder, state } = setup({ supported: ["audio/mp4"] });
    recorder.start(60_000);
    await settle();
    recorder.stop();
    const final = state();
    expect(final.status === "recorded" && final.recording.extension).toBe(".m4a");
  });

  it("stops by itself at the length limit and says so", async () => {
    const { recorder, state, advance, microphoneReleased } = setup();
    recorder.start(10_000);
    await settle();
    advance(9_000);
    expect(state().status).toBe("recording");
    advance(1_000);

    const final = state();
    expect(final.status).toBe("recorded");
    expect(final.status === "recorded" && final.recording.reachedLimit).toBe(true);
    expect(microphoneReleased()).toBe(true);
  });

  it("ignores a second start while already recording", async () => {
    const { recorder, getUserMedia } = setup();
    recorder.start(60_000);
    recorder.start(60_000);
    await settle();
    recorder.start(60_000);
    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("can record again after a recording", async () => {
    const { recorder, state, created } = setup();
    recorder.start(60_000);
    await settle();
    recorder.stop();
    recorder.start(60_000);
    await settle();
    expect(state().status).toBe("recording");
    expect(created).toHaveLength(2);
  });
});

describe("discarding", () => {
  it("throws away a finished recording", async () => {
    const { recorder, state } = setup();
    recorder.start(60_000);
    await settle();
    recorder.stop();
    recorder.discard();
    expect(state()).toEqual({ status: "idle" });
  });

  it("abandons a recording in progress without producing one, and releases the microphone", async () => {
    const { recorder, state, microphoneReleased } = setup();
    recorder.start(60_000);
    await settle();
    recorder.discard();
    expect(state()).toEqual({ status: "idle" });
    expect(microphoneReleased()).toBe(true);
  });

  it("releases the microphone if permission is granted after the user has given up", async () => {
    const { recorder, state, microphoneReleased, created } = setup();
    recorder.start(60_000); // the permission prompt is showing
    recorder.discard();
    await settle(); // ...and now it is answered
    expect(state()).toEqual({ status: "idle" });
    expect(created).toHaveLength(0);
    expect(microphoneReleased()).toBe(true);
  });
});

describe("problems are reported, never passed off as a recording", () => {
  const named = (name: string) => Object.assign(new Error(name), { name });

  it.each([
    ["NotAllowedError", "permission_denied"],
    ["SecurityError", "permission_denied"],
    ["NotFoundError", "no_microphone"],
    ["NotReadableError", "microphone_busy"],
    ["SomethingElse", "failed"],
  ])("%s becomes %s", async (errorName, code) => {
    const { recorder, state, getUserMedia } = setup();
    getUserMedia.mockRejectedValue(named(errorName));
    recorder.start(60_000);
    await settle();
    const final = state();
    expect(final.status).toBe("error");
    expect(final.status === "error" && final.code).toBe(code);
    expect(final.status === "error" && final.message.length).toBeGreaterThan(20);
  });

  it("reports an empty capture as an error", async () => {
    const { recorder, state, created, microphoneReleased } = setup();
    recorder.start(60_000);
    await settle();
    created[0].captured = [];
    recorder.stop();
    expect(state()).toMatchObject({ status: "error", code: "empty" });
    expect(microphoneReleased()).toBe(true);
  });

  it("reports a browser without recording support", async () => {
    const { recorder, state } = setup({ noDevices: true });
    recorder.start(60_000);
    await settle();
    expect(state()).toMatchObject({ status: "error", code: "unsupported" });
  });

  it("reports an insecure page before asking for the microphone", async () => {
    const { recorder, state, getUserMedia } = setup({ secure: false });
    recorder.start(60_000);
    await settle();
    expect(state()).toMatchObject({ status: "error", code: "insecure_context" });
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("reports a recorder that fails part-way and releases the microphone", async () => {
    const { recorder, state, created, microphoneReleased } = setup();
    recorder.start(60_000);
    await settle();
    created[0].onerror?.(new Event("error"));
    expect(state()).toMatchObject({ status: "error", code: "failed" });
    expect(microphoneReleased()).toBe(true);
  });

  it("lets the user try again after an error", async () => {
    const { recorder, state, getUserMedia } = setup();
    getUserMedia.mockRejectedValueOnce(named("NotAllowedError"));
    recorder.start(60_000);
    await settle();
    recorder.start(60_000);
    await settle();
    expect(state().status).toBe("recording");
  });
});

describe("extensionFor", () => {
  it("matches the file extension to the recorded format", () => {
    expect(extensionFor("audio/webm;codecs=opus")).toBe(".webm");
    expect(extensionFor("audio/mp4")).toBe(".m4a");
    expect(extensionFor("audio/ogg;codecs=opus")).toBe(".ogg");
    expect(extensionFor("")).toBe(".webm");
  });
});
