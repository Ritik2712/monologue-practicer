import { describe, expect, it } from "vitest";

import { compareAttempts, earlierAttempts } from "./compare";
import {
  formatBytes,
  formatDelta,
  formatMetric,
  formatNumber,
  formatPercent,
  formatSpan,
  formatTimecode,
  languageName,
  profileName,
  UNAVAILABLE,
} from "./format";
import {
  formatTick,
  labelFits,
  loudnessScale,
  momentAt,
  nearestPoint,
  pointTimes,
  timeTicks,
  unit,
} from "./timeline";
import type {
  AnalysisSummary,
  MetricValue,
  PauseEvent,
  SpeechSegment,
  UploadLimits,
} from "./types";
import { acceptAttribute, fileExtension, validateAudioFile } from "./validation";

const metric = (value: number | null, quality: MetricValue["quality"] = "measured"): MetricValue => ({
  value,
  unit: "",
  quality: value === null ? "unavailable" : quality,
  note: null,
});

describe("formatting", () => {
  it("writes positions in the recording as m:ss.s", () => {
    expect(formatTimecode(0)).toBe("0:00.0");
    expect(formatTimecode(4.706)).toBe("0:04.7");
    expect(formatTimecode(59.96)).toBe("1:00.0");
    expect(formatTimecode(723.04)).toBe("12:03.0");
    expect(formatTimecode(-1)).toBe("0:00.0");
  });

  it("writes lengths of time in seconds, then minutes", () => {
    expect(formatSpan(0.836)).toBe("0.8 s");
    expect(formatSpan(17.063)).toBe("17.1 s");
    expect(formatSpan(133.3)).toBe("2 min 13 s");
  });

  it("never shows a missing value as zero", () => {
    expect(formatNumber(null)).toBe(UNAVAILABLE);
    expect(formatNumber(undefined)).toBe(UNAVAILABLE);
    expect(formatMetric(metric(null))).toBe(UNAVAILABLE);
    expect(formatMetric(undefined)).toBe(UNAVAILABLE);
    expect(formatPercent(null)).toBe(UNAVAILABLE);
    expect(formatNumber(0)).toBe("0.0");
  });

  it("formats numbers, percentages and sizes", () => {
    expect(formatNumber(223.14)).toBe("223.1");
    expect(formatNumber(1234.5, 0)).toBe("1,235");
    expect(formatMetric(metric(3), 0)).toBe("3");
    expect(formatPercent(0.5033)).toBe("50%");
    expect(formatBytes(756_574)).toBe("739 KB");
    expect(formatBytes(5_880_496)).toBe("5.6 MB");
    expect(formatBytes(10)).toBe("1 KB");
  });

  it("always signs a change", () => {
    expect(formatDelta(12.34)).toBe("+12.3");
    expect(formatDelta(-4)).toBe("−4.0");
    expect(formatDelta(0.04)).toBe("±0.0");
    expect(formatDelta(-0.04)).toBe("±0.0");
    expect(formatDelta(2, 0)).toBe("+2");
  });

  it("names profiles and languages", () => {
    expect(profileName("thomas_shelby")).toBe("Thomas Shelby");
    expect(languageName("hi")).toBe("Hindi");
    expect(languageName("ur")).toBe("UR");
  });
});

describe("file checks", () => {
  const limits: UploadLimits = {
    maxUploadBytes: 50 * 1024 * 1024,
    maxAudioSeconds: 600,
    acceptedExtensions: [".m4a", ".mp3", ".wav", ".webm"],
  };

  it("accepts a known extension or an audio content type", () => {
    expect(validateAudioFile({ name: "take.MP3", type: "", size: 1000 }, limits)).toEqual({ ok: true });
    expect(validateAudioFile({ name: "blob", type: "audio/ogg", size: 1000 }, limits)).toEqual({
      ok: true,
    });
  });

  it("explains a file that is not audio, listing what is accepted", () => {
    const result = validateAudioFile({ name: "notes.pdf", type: "application/pdf", size: 1000 }, limits);
    expect(result).toEqual({
      ok: false,
      message: "This does not look like an audio file. Accepted types: M4A, MP3, WAV, WEBM.",
    });
  });

  it("refuses empty and oversized files with the sizes in the message", () => {
    expect(validateAudioFile({ name: "a.wav", type: "audio/wav", size: 0 }, limits)).toEqual({
      ok: false,
      message: "This file is empty.",
    });
    expect(
      validateAudioFile({ name: "a.wav", type: "audio/wav", size: 60 * 1024 * 1024 }, limits),
    ).toEqual({ ok: false, message: "This file is 60.0 MB. The limit is 50.0 MB." });
    expect(
      validateAudioFile({ name: "a.wav", type: "audio/wav", size: limits.maxUploadBytes }, limits),
    ).toEqual({ ok: true });
  });

  it("reads extensions and builds the file picker filter", () => {
    expect(fileExtension("My Take.Final.M4A")).toBe(".m4a");
    expect(fileExtension("noextension")).toBe("");
    expect(fileExtension(".hidden")).toBe("");
    expect(acceptAttribute(limits)).toBe("audio/*,.m4a,.mp3,.wav,.webm");
  });
});

describe("comparing attempts", () => {
  it("reports the change in each metric without judging it", () => {
    const rows = compareAttempts(
      { speechActiveWpm: metric(160), pauseCount: metric(5), pauseRatio: metric(0.3) },
      { speechActiveWpm: metric(182.5), pauseCount: metric(3), pauseRatio: metric(0.25) },
    );
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));

    expect(byKey.speechActiveWpm).toMatchObject({ current: 160, previous: 182.5, delta: -22.5 });
    expect(byKey.pauseCount).toMatchObject({ current: 5, previous: 3, delta: 2 });
    // Ratios are compared as percentages.
    expect(byKey.pauseRatio.current).toBeCloseTo(30);
    expect(byKey.pauseRatio.delta).toBeCloseTo(5);
    expect(rows.every((row) => !("better" in row))).toBe(true);
  });

  it("subtracts the rounded values that are shown, so the columns add up", () => {
    const rows = compareAttempts({ pauseRatio: metric(0.316) }, { pauseRatio: metric(0.503) });
    const row = rows.find((item) => item.key === "pauseRatio");
    // Shown as 32% and 50%: the change must read -18, not the -19 of the unrounded values.
    expect(row).toMatchObject({ current: 32, previous: 50, delta: -18 });
  });

  it("leaves the change empty when either side could not be measured", () => {
    const rows = compareAttempts(
      { speechActiveWpm: metric(160), pitchVariationSemitones: metric(null) },
      { pitchVariationSemitones: metric(2.5) },
    );
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));
    expect(byKey.speechActiveWpm).toMatchObject({ current: 160, previous: null, delta: null });
    expect(byKey.pitchVariationSemitones).toMatchObject({ current: null, previous: 2.5, delta: null });
  });

  it("marks a difference as an estimate when either value is one", () => {
    const [row] = compareAttempts(
      { speechActiveWpm: metric(160, "estimated") },
      { speechActiveWpm: metric(150) },
    );
    expect(row.estimated).toBe(true);
  });

  it("offers only earlier attempts, newest first", () => {
    const item = (analysisId: string, createdAt: string) => ({ analysisId, createdAt }) as AnalysisSummary;
    const history = [
      item("c", "2026-10-11T10:00:00Z"),
      item("b", "2026-10-11T09:00:00Z"),
      item("d", "2026-10-11T11:00:00Z"),
      item("a", "2026-10-10T09:00:00Z"),
    ];
    const earlier = earlierAttempts(history, "c", "2026-10-11T10:00:00Z");
    expect(earlier.map((entry) => entry.analysisId)).toEqual(["b", "a"]);
    expect(earlierAttempts(history, "a", "2026-10-10T09:00:00Z")).toEqual([]);
  });
});

describe("timeline arithmetic", () => {
  it("picks round tick steps that suit the length", () => {
    expect(timeTicks(17.06, 8)).toEqual([0, 5, 10, 15]);
    expect(timeTicks(133.3, 8)).toEqual([0, 30, 60, 90, 120]);
    expect(timeTicks(4, 8)).toEqual([0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4]);
    expect(timeTicks(0, 8)).toEqual([0]);
  });

  it("labels ticks in seconds, or minutes for longer recordings", () => {
    expect(formatTick(5, 17)).toBe("5s");
    expect(formatTick(0.5, 4)).toBe("0.5s");
    expect(formatTick(90, 133)).toBe("1:30");
    expect(formatTick(0, 133)).toBe("0:00");
  });

  it("fits the loudness axis to the loudest moment with clean values", () => {
    expect(loudnessScale([-100, -32.4, -14.6])).toEqual({
      minDb: -60,
      maxDb: -10,
      ticks: [-60, -50, -40, -30, -20, -10],
    });
    expect(loudnessScale([-3.2]).maxDb).toBe(0);
    expect(loudnessScale([]).maxDb).toBe(0);
  });

  it("clamps values outside the chart instead of drawing them off it", () => {
    expect(unit(-100, -60, -10)).toBe(0);
    expect(unit(-35, -60, -10)).toBe(0.5);
    expect(unit(5, -60, -10)).toBe(1);
    expect(unit(1, 2, 2)).toBe(0);
  });

  it("finds the loudness point nearest a moment", () => {
    expect(pointTimes({ energyTimeline: { secondsPerPoint: 0.25, unit: "", values: [1, 2, 3] } })).toEqual(
      [0.125, 0.375, 0.625],
    );
    expect(nearestPoint(0, 0.25, 68)).toBe(0);
    expect(nearestPoint(0.4, 0.25, 68)).toBe(1);
    expect(nearestPoint(999, 0.25, 68)).toBe(67);
    expect(nearestPoint(1, 0.25, 0)).toBe(-1);
  });

  it("says what is happening at a moment", () => {
    const segments = [
      { id: "seg-1", startSeconds: 1, endSeconds: 3 },
      { id: "seg-2", startSeconds: 4.5, endSeconds: 8 },
    ] as SpeechSegment[];
    const pauses = [{ id: "pause-1", startSeconds: 3, endSeconds: 4.5 }] as PauseEvent[];
    const analysis = { segments, pauses };

    expect(momentAt(2, analysis)).toMatchObject({ kind: "segment", segment: { id: "seg-1" } });
    expect(momentAt(3.7, analysis)).toMatchObject({ kind: "pause", pause: { id: "pause-1" } });
    expect(momentAt(0.2, analysis)).toEqual({ kind: "silence", position: "before" });
    expect(momentAt(9, analysis)).toEqual({ kind: "silence", position: "after" });
    expect(momentAt(2, { segments: [], pauses: [] })).toEqual({ kind: "empty" });
  });

  it("says a moment inside a phrase's own pause is a pause", () => {
    // One phrase from 1 s to 6 s, holding a pause from 3 s to 3.6 s.
    const analysis = {
      segments: [{ id: "seg-1", startSeconds: 1, endSeconds: 6 }] as SpeechSegment[],
      pauses: [{ id: "pause-1", startSeconds: 3, endSeconds: 3.6, insideSegment: true }] as PauseEvent[],
    };
    expect(momentAt(3.3, analysis)).toMatchObject({ kind: "pause", pause: { id: "pause-1" } });
    expect(momentAt(2, analysis)).toMatchObject({ kind: "segment", segment: { id: "seg-1" } });
    expect(momentAt(4, analysis)).toMatchObject({ kind: "segment", segment: { id: "seg-1" } });
  });

  it("compares attempts on delivery pace, reading an older result's one pace as that", () => {
    const rows = compareAttempts(
      { deliveryWpm: metric(140), speechActiveWpm: metric(150) },
      { speechActiveWpm: metric(182.5) },
    );
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));
    expect(byKey.deliveryWpm).toMatchObject({ current: 140, previous: 182.5, delta: -42.5 });
    expect(byKey.speechActiveWpm).toMatchObject({ current: 150, previous: 182.5 });
    // A result that stored the metric as empty is read the same way as one without it.
    const stored = compareAttempts({ deliveryWpm: null, speechActiveWpm: metric(160) }, {});
    expect(stored.find((row) => row.key === "deliveryWpm")?.current).toBe(160);
  });

  it("only places a label where it fits with padding", () => {
    expect(labelFits("6.1 s", 60)).toBe(true);
    expect(labelFits("6.1 s", 30)).toBe(false);
    expect(labelFits("", 12)).toBe(true);
  });
});
