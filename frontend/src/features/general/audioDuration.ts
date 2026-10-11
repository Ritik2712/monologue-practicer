/**
 * Recordings made by the browser's MediaRecorder carry no length. An <audio> element then
 * reports a duration of Infinity and cannot jump to a position, so "play this segment" does
 * nothing.
 *
 * The standard remedy: ask the element to jump far past the end. That forces the browser to
 * read through the recording and work its length out. Once it has, playback is put back at
 * the start and jumping around works normally.
 */

type AudioLike = Pick<
  HTMLAudioElement,
  "duration" | "currentTime" | "addEventListener" | "removeEventListener"
>;

/** Elements currently being fixed, so the remedy is never started twice on one element. */
const inProgress = new WeakSet<object>();

const FAR_PAST_THE_END = 1e101;

/**
 * Starts the fix if the element's length is unknown. Safe to call on every metadata or
 * duration event. `onResolved` runs once the length is known and playback is back at 0.
 */
export function resolveUnknownDuration(audio: AudioLike, onResolved?: () => void): void {
  if (audio.duration !== Infinity || inProgress.has(audio)) return;
  inProgress.add(audio);

  const check = () => {
    // The browser emits several events while it reads; only stop once the length is real.
    if (!Number.isFinite(audio.duration)) return;
    audio.removeEventListener("timeupdate", check);
    audio.removeEventListener("durationchange", check);
    inProgress.delete(audio);
    audio.currentTime = 0;
    onResolved?.();
  };
  audio.addEventListener("timeupdate", check);
  audio.addEventListener("durationchange", check);
  audio.currentTime = FAR_PAST_THE_END;
}

/** True while the fix above is running, when the element's reported time is meaningless. */
export function isResolvingDuration(audio: object): boolean {
  return inProgress.has(audio);
}
