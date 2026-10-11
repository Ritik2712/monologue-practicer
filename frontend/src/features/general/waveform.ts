/**
 * The arithmetic behind the waveform comparison. Drawing only: nothing here feeds a
 * measurement, and nothing here is sent anywhere.
 */
import { timeTicks } from "./timeline";
import type { Waveform } from "./types";

/** One pixel-wide slice of a drawn waveform: the lowest and highest value in it. */
export type Column = { x: number; low: number; high: number };

export type TimeSpan = { fromSeconds: number; toSeconds: number };

/**
 * The stretch of time both recordings fit into, in seconds.
 *
 * Each keeps its real length. The take can be shifted by `offsetSeconds`; a negative
 * shift moves it left, so the span then starts before zero.
 */
export function sharedSpan(
  referenceSeconds: number | null,
  takeSeconds: number | null,
  offsetSeconds: number,
): TimeSpan {
  const takeStart = takeSeconds === null ? 0 : offsetSeconds;
  const takeEnd = takeSeconds === null ? 0 : takeSeconds + offsetSeconds;
  const fromSeconds = Math.min(0, takeStart);
  const toSeconds = Math.max(referenceSeconds ?? 0, takeEnd, fromSeconds + 1);
  return { fromSeconds, toSeconds };
}

/** Keeps a shift within reach: the take may slide until it only just touches the reference. */
export function clampOffset(
  offsetSeconds: number,
  referenceSeconds: number,
  takeSeconds: number,
): number {
  if (!Number.isFinite(offsetSeconds)) return 0;
  const rounded = Math.round(offsetSeconds * 10) / 10;
  return Math.min(Math.floor(referenceSeconds), Math.max(-Math.floor(takeSeconds), rounded));
}

/** The loudest point of an outline, from 0 to 1. */
export function peakOf(outline: Waveform): number {
  let peak = 0;
  for (let i = 0; i < outline.maximum.length; i += 1) {
    peak = Math.max(peak, Math.abs(outline.maximum[i]), Math.abs(outline.minimum[i]));
  }
  return peak;
}

/**
 * Reduces an outline to one low/high pair per pixel column.
 *
 * The outline can hold more points than the chart has pixels, so points that land in the
 * same column are merged by taking the lowest low and the highest high. `gain` multiplies
 * the values (1 leaves them as recorded); results are kept within -1 to 1.
 */
export function outlineColumns(
  outline: Waveform,
  span: TimeSpan,
  width: number,
  offsetSeconds = 0,
  gain = 1,
): Column[] {
  const length = span.toSeconds - span.fromSeconds;
  if (width <= 0 || length <= 0) return [];
  const columns = new Map<number, Column>();
  for (let i = 0; i < outline.maximum.length; i += 1) {
    const middle = (i + 0.5) * outline.secondsPerPoint + offsetSeconds;
    const x = Math.floor(((middle - span.fromSeconds) / length) * width);
    if (x < 0 || x >= width) continue;
    const low = Math.max(-1, outline.minimum[i] * gain);
    const high = Math.min(1, outline.maximum[i] * gain);
    const column = columns.get(x);
    if (column) {
      column.low = Math.min(column.low, low);
      column.high = Math.max(column.high, high);
    } else {
      columns.set(x, { x, low, high });
    }
  }
  return [...columns.values()].sort((a, b) => a.x - b.x);
}

/**
 * An SVG path for a waveform drawn as a filled band: along the top edge, then back along
 * the bottom. `top` and `height` place the band; its middle line is silence.
 */
export function bandPath(columns: Column[], left: number, top: number, height: number): string {
  if (columns.length === 0) return "";
  const middle = top + height / 2;
  const y = (value: number) => (middle - (value * height) / 2).toFixed(1);
  // A band always has some thickness, so silence still shows as a thin line.
  const upper = columns.map(({ x, high }) => `${left + x},${y(Math.max(high, 0.004))}`);
  const lower = [...columns]
    .reverse()
    .map(({ x, low }) => `${left + x + 1},${y(Math.min(low, -0.004))}`);
  return `M${upper.join("L")}L${lower.join("L")}Z`;
}

/** The moment, in seconds on the shared timeline, under a pixel position. */
export function timeAtPixel(x: number, span: TimeSpan, width: number): number {
  if (width <= 0) return span.fromSeconds;
  const share = Math.min(1, Math.max(0, x / width));
  return span.fromSeconds + share * (span.toSeconds - span.fromSeconds);
}

/**
 * Where a moment on the shared timeline falls inside one recording, or null if that
 * recording is not sounding then.
 */
export function ownTime(
  sharedSeconds: number,
  durationSeconds: number,
  offsetSeconds = 0,
): number | null {
  const own = sharedSeconds - offsetSeconds;
  return own < 0 || own > durationSeconds ? null : own;
}

/**
 * Round tick values across a span that may start before zero (a take shifted earlier).
 * They are multiples of one step, so 0 is always among them when it is in view.
 */
export function spanTicks(span: TimeSpan, maxTicks: number): number[] {
  const fromZero = timeTicks(span.toSeconds - span.fromSeconds, maxTicks);
  const step = fromZero.length > 1 ? fromZero[1] - fromZero[0] : 1;
  const ticks: number[] = [];
  for (let tick = Math.ceil(span.fromSeconds / step) * step; tick <= span.toSeconds; tick += step) {
    // Adding zero turns a "-0" into a plain 0.
    ticks.push(Number(tick.toFixed(3)) + 0);
  }
  return ticks;
}
