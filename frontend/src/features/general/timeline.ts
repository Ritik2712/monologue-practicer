/**
 * The arithmetic behind the timeline chart: scales, axis ticks, and "what is at this moment".
 * No drawing here, so it can be tested without a browser.
 */
import type { AnalysisResult, PauseEvent, SpeechSegment } from "./types";

/** How far below the loudest moment the loudness chart reaches. Quieter is drawn at the floor. */
export const LOUDNESS_SPAN_DB = 50;
/** Rough width of one character of an 11px label, for deciding whether a label fits. */
const LABEL_CHAR_PX = 6.2;

const TIME_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

/** Evenly spaced, round tick positions from 0 up to (and not beyond) `max`. */
export function timeTicks(durationSeconds: number, targetCount: number): number[] {
  if (durationSeconds <= 0) return [0];
  const step =
    TIME_STEPS.find((candidate) => durationSeconds / candidate <= targetCount) ??
    TIME_STEPS[TIME_STEPS.length - 1];
  const ticks: number[] = [];
  for (let tick = 0; tick <= durationSeconds + 1e-9; tick += step) ticks.push(Number(tick.toFixed(1)));
  return ticks;
}

/** Axis labels: whole seconds for short clips, m:ss once there are minutes. */
export function formatTick(seconds: number, durationSeconds: number): string {
  if (durationSeconds < 60) return `${Number.isInteger(seconds) ? seconds : seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
}

export type LoudnessScale = {
  /** Bottom and top of the chart, in dB. Both multiples of 10. */
  minDb: number;
  maxDb: number;
  ticks: number[];
};

/** A dB range that fits the loudest moment, with clean tick values. */
export function loudnessScale(values: number[]): LoudnessScale {
  const peak = values.length ? Math.max(...values) : 0;
  // Adding 0 turns the -0 that rounding can produce into a plain 0, so no tick reads "-0".
  const maxDb = Math.min(0, Math.ceil(peak / 10) * 10) + 0;
  const minDb = maxDb - LOUDNESS_SPAN_DB;
  const ticks: number[] = [];
  for (let tick = minDb; tick <= maxDb; tick += 10) ticks.push(tick);
  return { minDb, maxDb, ticks };
}

/** Maps a value in [min, max] to [0, 1], clamping whatever falls outside. */
export function unit(value: number, min: number, max: number): number {
  if (max <= min) return 0;
  return Math.min(1, Math.max(0, (value - min) / (max - min)));
}

/** The moment at the centre of each loudness point. */
export function pointTimes(analysis: Pick<AnalysisResult, "energyTimeline">): number[] {
  const { secondsPerPoint, values } = analysis.energyTimeline;
  return values.map((_, index) => (index + 0.5) * secondsPerPoint);
}

/** Index of the loudness point nearest to a moment. -1 when there are no points. */
export function nearestPoint(seconds: number, secondsPerPoint: number, count: number): number {
  if (count === 0 || secondsPerPoint <= 0) return -1;
  return Math.min(count - 1, Math.max(0, Math.round(seconds / secondsPerPoint - 0.5)));
}

export type Moment =
  | { kind: "segment"; segment: SpeechSegment }
  | { kind: "pause"; pause: PauseEvent }
  /** Silence before the first word or after the last one. */
  | { kind: "silence"; position: "before" | "after" }
  | { kind: "empty" };

/** What is happening at a moment of the recording: speaking, pausing, or neither yet. */
export function momentAt(
  seconds: number,
  analysis: Pick<AnalysisResult, "segments" | "pauses">,
): Moment {
  // A pause first: a short one lies inside its phrase, and a moment in it is a pause.
  const pause = analysis.pauses.find(
    (item) => seconds > item.startSeconds && seconds < item.endSeconds,
  );
  if (pause) return { kind: "pause", pause };
  const segment = analysis.segments.find(
    (item) => seconds >= item.startSeconds && seconds <= item.endSeconds,
  );
  if (segment) return { kind: "segment", segment };
  if (analysis.segments.length === 0) return { kind: "empty" };
  return {
    kind: "silence",
    position: seconds < analysis.segments[0].startSeconds ? "before" : "after",
  };
}

/** Whether a short text label fits inside a gap of the given width, with padding. */
export function labelFits(text: string, widthPx: number, paddingPx = 6): boolean {
  return text.length * LABEL_CHAR_PX + paddingPx * 2 <= widthPx;
}
