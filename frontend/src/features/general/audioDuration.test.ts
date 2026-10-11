import { describe, expect, it, vi } from "vitest";

import { isResolvingDuration, resolveUnknownDuration } from "./audioDuration";

/** Behaves like an <audio> element as far as this fix is concerned. */
function fakeAudio(duration: number) {
  const target = new EventTarget();
  const audio = {
    duration,
    currentTime: 0,
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    emit: (name: string) => target.dispatchEvent(new Event(name)),
  };
  return audio as typeof audio & HTMLAudioElement;
}

describe("resolveUnknownDuration", () => {
  it("leaves an element alone when its length is already known", () => {
    const audio = fakeAudio(17.06);
    const done = vi.fn();
    resolveUnknownDuration(audio, done);
    expect(audio.currentTime).toBe(0);
    expect(isResolvingDuration(audio)).toBe(false);
    expect(done).not.toHaveBeenCalled();
  });

  it("jumps far past the end, waits for a real length, then returns to the start", () => {
    const audio = fakeAudio(Infinity);
    const done = vi.fn();
    resolveUnknownDuration(audio, done);
    expect(audio.currentTime).toBe(1e101);
    expect(isResolvingDuration(audio)).toBe(true);

    // The browser reports progress before it knows the length: keep waiting.
    audio.emit("durationchange");
    audio.emit("timeupdate");
    expect(audio.currentTime).toBe(1e101);
    expect(done).not.toHaveBeenCalled();

    audio.duration = 16.977;
    audio.currentTime = 16.977;
    audio.emit("timeupdate");
    expect(audio.currentTime).toBe(0);
    expect(isResolvingDuration(audio)).toBe(false);
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("stops listening once it is done", () => {
    const audio = fakeAudio(Infinity);
    const done = vi.fn();
    resolveUnknownDuration(audio, done);
    audio.duration = 10;
    audio.emit("durationchange");

    audio.currentTime = 4.7; // the user is now playing normally
    audio.emit("timeupdate");
    audio.emit("durationchange");
    expect(audio.currentTime).toBe(4.7);
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("is not started twice on the same element", () => {
    const audio = fakeAudio(Infinity);
    const done = vi.fn();
    resolveUnknownDuration(audio, done);
    resolveUnknownDuration(audio, done);
    audio.duration = 10;
    audio.emit("timeupdate");
    expect(done).toHaveBeenCalledTimes(1);
  });
});
