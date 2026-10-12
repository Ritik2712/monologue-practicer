import { describe, expect, it } from "vitest";

import type { SpeechSegment, VoiceMarker, VoicePlacement, VoiceRange } from "./types";
import {
  edgesOf,
  goalSummary,
  isOutsideGoal,
  phraseCountsText,
  phrasesOutsideGoal,
  positionText,
  rangeText,
  scalePosition,
  scaleWidths,
} from "./voiceRange";

const BANDS = {
  version: 1,
  pitch_low_end_hz: 85,
  pitch_neutral_from_hz: 145,
  pitch_neutral_to_hz: 175,
  pitch_high_end_hz: 255,
  resonance_low_end_hz: 940,
  resonance_neutral_from_hz: 1040,
  resonance_neutral_to_hz: 1100,
  resonance_high_end_hz: 1300,
};
const PITCH = { lowEnd: 85, neutralFrom: 145, neutralTo: 175, highEnd: 255 };

const placement = (band: VoicePlacement["band"], percent: number): VoicePlacement => ({
  valueHz: 120,
  band,
  percent,
  quality: "measured",
});
const phrase = (index: number, marker: VoiceMarker | null) =>
  ({
    id: `seg-${index + 1}`,
    index,
    voice: marker === null ? null : { pitch: null, resonance: null, marker },
  }) as SpeechSegment;
const voice = (goal: VoiceRange["goal"]): VoiceRange => ({
  goal,
  pitch: null,
  resonance: null,
  marker: null,
  formantsHz: null,
  phrases: { lower: 0, neutral: 0, higher: 0, mixed: 0, unmeasured: 0 },
  bands: BANDS,
  resonanceNote: null,
});

describe("the ranges", () => {
  it("are read from the result, one set per scale", () => {
    expect(edgesOf(BANDS, "pitch")).toEqual(PITCH);
    expect(edgesOf(BANDS, "resonance")).toEqual({
      lowEnd: 940,
      neutralFrom: 1040,
      neutralTo: 1100,
      highEnd: 1300,
    });
  });

  it("are not guessed when the result does not carry them", () => {
    expect(edgesOf({ version: 1 }, "pitch")).toBeNull();
  });

  it("are put into words", () => {
    expect(rangeText("lower", PITCH)).toBe("under 145 Hz");
    expect(rangeText("neutral", PITCH)).toBe("145 to 175 Hz");
    expect(rangeText("higher", PITCH)).toBe("over 175 Hz");
  });
});

describe("the percentage", () => {
  it("is worded as a position inside the range", () => {
    expect(positionText(placement("lower", 45))).toBe("45% of the way into it");
    expect(positionText(placement("higher", 31))).toBe("31% of the way into it");
  });

  it("is worded differently for the neutral range, which counts towards its middle", () => {
    expect(positionText(placement("neutral", 80))).toBe("80% of the way to its middle");
  });
});

describe("the bar", () => {
  it("draws the three ranges in proportion to their width", () => {
    const widths = scaleWidths(PITCH);
    // 60, 30 and 80 Hz of a 170 Hz scale.
    expect(widths.lower).toBeCloseTo(60 / 170);
    expect(widths.neutral).toBeCloseTo(30 / 170);
    expect(widths.higher).toBeCloseTo(80 / 170);
    expect(widths.lower + widths.neutral + widths.higher).toBeCloseTo(1);
  });

  it("puts the mark where the value falls, and at the end for a value beyond it", () => {
    expect(scalePosition(85, PITCH)).toBe(0);
    expect(scalePosition(170, PITCH)).toBeCloseTo(0.5);
    expect(scalePosition(255, PITCH)).toBe(1);
    expect(scalePosition(60, PITCH)).toBe(0);
    expect(scalePosition(400, PITCH)).toBe(1);
  });
});

describe("the goal", () => {
  const segments = [
    phrase(0, "lower"),
    phrase(1, "neutral"),
    phrase(2, "mixed"),
    phrase(3, "lower"),
    phrase(4, null),
  ];

  it("marks nothing when there is no goal", () => {
    expect(phrasesOutsideGoal(segments, "none")).toEqual([]);
    expect(isOutsideGoal("higher", "none")).toBe(false);
    expect(goalSummary(voice("none"), segments)).toBeNull();
  });

  it("marks the measured phrases that sat anywhere but the range aimed for", () => {
    expect(phrasesOutsideGoal(segments, "lower").map((item) => item.id)).toEqual(["seg-2", "seg-3"]);
    expect(phrasesOutsideGoal(segments, "higher")).toHaveLength(4);
    // A phrase that could not be measured is not held against the goal.
    expect(isOutsideGoal(null, "lower")).toBe(false);
    expect(isOutsideGoal(undefined, "lower")).toBe(false);
  });

  it("is summed up in a sentence that counts only what was measured", () => {
    expect(goalSummary(voice("lower"), segments)).toBe(
      "Your goal is to keep your voice in the lower range. 2 of 4 phrases stayed in it; the 2 that did not are marked below.",
    );
    expect(goalSummary(voice("lower"), [phrase(0, "lower"), phrase(1, "lower")])).toBe(
      "Your goal is to keep your voice in the lower range. 2 of 2 phrases stayed in it.",
    );
    expect(goalSummary(voice("higher"), [phrase(0, "higher"), phrase(1, "mixed")])).toBe(
      "Your goal is to keep your voice in the higher range. 1 of 2 phrases stayed in it; the one that did not is marked below.",
    );
  });

  it("says so when nothing could be placed", () => {
    expect(goalSummary(voice("lower"), [phrase(0, null)])).toBe(
      "Your goal is to keep your voice in the lower range. No phrase could be placed, so there is nothing to set against it.",
    );
  });
});

describe("the count of phrases", () => {
  it("lists only the markers that occur, and what was not measured", () => {
    expect(phraseCountsText({ lower: 5, neutral: 2, higher: 0, mixed: 1, unmeasured: 0 })).toBe(
      "5 lower, 2 neutral, 1 mixed",
    );
    expect(phraseCountsText({ lower: 0, neutral: 0, higher: 3, mixed: 0, unmeasured: 2 })).toBe(
      "3 higher, 2 not measured",
    );
  });
});
