import { describe, expect, it } from "vitest";

import type { Waveform } from "./types";
import {
  bandPath,
  clampOffset,
  outlineColumns,
  ownTime,
  peakOf,
  sharedSpan,
  spanTicks,
  timeAtPixel,
} from "./waveform";

const outline = (values: [number, number][], secondsPerPoint = 1): Waveform => ({
  durationSeconds: values.length * secondsPerPoint,
  secondsPerPoint,
  minimum: values.map(([low]) => low),
  maximum: values.map(([, high]) => high),
});

describe("the shared timeline", () => {
  it("is as long as the longer recording, and neither is stretched to match", () => {
    expect(sharedSpan(17.1, 22.5, 0)).toEqual({ fromSeconds: 0, toSeconds: 22.5 });
    expect(sharedSpan(30, 12, 0)).toEqual({ fromSeconds: 0, toSeconds: 30 });
  });

  it("grows when the take is shifted", () => {
    expect(sharedSpan(17, 22, 3)).toEqual({ fromSeconds: 0, toSeconds: 25 });
    // Shifted left, the take starts before the reference does.
    expect(sharedSpan(17, 10, -4)).toEqual({ fromSeconds: -4, toSeconds: 17 });
  });

  it("works with only one recording", () => {
    expect(sharedSpan(17, null, 5)).toEqual({ fromSeconds: 0, toSeconds: 17 });
    expect(sharedSpan(null, 9, 0)).toEqual({ fromSeconds: 0, toSeconds: 9 });
  });

  it("keeps a shift within reach of the reference, in steps of a tenth of a second", () => {
    expect(clampOffset(1.234, 17.1, 22.5)).toBe(1.2);
    expect(clampOffset(99, 17.1, 22.5)).toBe(17);
    expect(clampOffset(-99, 17.1, 22.5)).toBe(-22);
    expect(clampOffset(Number.NaN, 17.1, 22.5)).toBe(0);
  });
});

describe("turning an outline into pixel columns", () => {
  it("gives each point its place on the timeline", () => {
    const columns = outlineColumns(outline([[-0.2, 0.3], [-0.5, 0.1]]), { fromSeconds: 0, toSeconds: 4 }, 4);
    // Two one-second points on a four-second, four-pixel timeline.
    expect(columns).toEqual([
      { x: 0, low: -0.2, high: 0.3 },
      { x: 1, low: -0.5, high: 0.1 },
    ]);
  });

  it("merges points that share a pixel, keeping the extremes", () => {
    const columns = outlineColumns(
      outline([[-0.1, 0.2], [-0.6, 0.1], [-0.2, 0.9], [-0.3, 0.3]]),
      { fromSeconds: 0, toSeconds: 4 },
      2,
    );
    expect(columns).toEqual([
      { x: 0, low: -0.6, high: 0.2 },
      { x: 1, low: -0.3, high: 0.9 },
    ]);
  });

  it("moves a shifted recording along the timeline without changing its length", () => {
    const span = { fromSeconds: 0, toSeconds: 4 };
    const shifted = outlineColumns(outline([[-0.2, 0.3], [-0.5, 0.1]]), span, 4, 2);
    expect(shifted.map((column) => column.x)).toEqual([2, 3]);
    // Shifted past the edge of the chart, the part outside is simply not drawn.
    expect(outlineColumns(outline([[-0.2, 0.3], [-0.5, 0.1]]), span, 4, 3).map((c) => c.x)).toEqual([3]);
  });

  it("leaves a quiet recording quiet unless it is deliberately stretched", () => {
    const quiet = outline([[-0.1, 0.1]]);
    const span = { fromSeconds: 0, toSeconds: 1 };
    expect(outlineColumns(quiet, span, 1)[0]).toEqual({ x: 0, low: -0.1, high: 0.1 });
    const stretched = outlineColumns(quiet, span, 1, 0, 1 / peakOf(quiet))[0];
    expect(stretched.low).toBeCloseTo(-1);
    expect(stretched.high).toBeCloseTo(1);
  });

  it("never draws beyond full scale", () => {
    const column = outlineColumns(outline([[-0.8, 0.9]]), { fromSeconds: 0, toSeconds: 1 }, 1, 0, 5)[0];
    expect(column).toEqual({ x: 0, low: -1, high: 1 });
  });

  it("has nothing to draw without room or without time", () => {
    expect(outlineColumns(outline([[-0.1, 0.1]]), { fromSeconds: 0, toSeconds: 1 }, 0)).toEqual([]);
    expect(outlineColumns(outline([[-0.1, 0.1]]), { fromSeconds: 2, toSeconds: 2 }, 100)).toEqual([]);
  });
});

describe("drawing and reading the chart", () => {
  it("finds the loudest point of an outline", () => {
    expect(peakOf(outline([[-0.2, 0.3], [-0.7, 0.1]]))).toBe(0.7);
    expect(peakOf(outline([]))).toBe(0);
  });

  it("draws a filled band: along the top, back along the bottom", () => {
    const path = bandPath(
      [
        { x: 0, low: -0.5, high: 0.5 },
        { x: 1, low: -1, high: 1 },
      ],
      10,
      0,
      100,
    );
    expect(path).toBe("M10,25.0L11,0.0L12,100.0L11,75.0Z");
    expect(bandPath([], 0, 0, 100)).toBe("");
  });

  it("shows silence as a thin line, not as nothing", () => {
    expect(bandPath([{ x: 0, low: 0, high: 0 }], 0, 0, 100)).toBe("M0,49.8L1,50.2Z");
  });

  it("reads the moment under the pointer", () => {
    const span = { fromSeconds: -4, toSeconds: 16 };
    expect(timeAtPixel(0, span, 200)).toBe(-4);
    expect(timeAtPixel(100, span, 200)).toBe(6);
    expect(timeAtPixel(999, span, 200)).toBe(16);
  });

  it("labels the time axis with round values, including before zero", () => {
    expect(spanTicks({ fromSeconds: 0, toSeconds: 22.5 }, 8)).toEqual([0, 5, 10, 15, 20]);
    expect(spanTicks({ fromSeconds: -4, toSeconds: 17 }, 8)).toEqual([0, 5, 10, 15]);
    expect(spanTicks({ fromSeconds: -12, toSeconds: 17 }, 8)).toEqual([-10, -5, 0, 5, 10, 15]);
  });

  it("says where that moment falls in each recording", () => {
    // 6 s on the shared timeline, with the take shifted 2 s to the right.
    expect(ownTime(6, 17)).toBe(6);
    expect(ownTime(6, 22, 2)).toBe(4);
    // Before the take has started, and after the reference has ended.
    expect(ownTime(1, 22, 2)).toBeNull();
    expect(ownTime(20, 17)).toBeNull();
  });
});
