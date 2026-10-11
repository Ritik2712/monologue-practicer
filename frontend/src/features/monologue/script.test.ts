import { describe, expect, it } from "vitest";

import type { AnalysisResult } from "@/features/general/types";

import { buildScript, emphasisText, scriptCounts } from "./script";

type ScriptSource = Parameters<typeof buildScript>[0];

const segment = (id: string, start: number, end: number, extra: object = {}) =>
  ({
    id,
    startSeconds: start,
    endSeconds: end,
    transcript: null,
    segmentWpm: null,
    paceVsTypical: null,
    ...extra,
  }) as AnalysisResult["segments"][number];
const word = (text: string, start: number, segmentId: string | null) =>
  ({ text, startSeconds: start, endSeconds: start + 0.3, confidence: 0.9, segmentId }) as AnalysisResult["words"][number];
const pause = (id: string, after: string, start: number, end: number, significance = "medium") =>
  ({
    id,
    afterSegmentId: after,
    startSeconds: start,
    endSeconds: end,
    durationSeconds: end - start,
    significance,
  }) as AnalysisResult["pauses"][number];

/** "I am not in danger, / I am the danger." with a pause between, and "danger." stressed. */
const recording: ScriptSource = {
  segments: [
    segment("seg-1", 0, 2, { segmentWpm: 150, paceVsTypical: "faster" }),
    segment("seg-2", 3.6, 5.5, { segmentWpm: 126.3 }),
  ],
  pauses: [pause("pause-1", "seg-1", 2, 3.6)],
  words: [
    word("I", 0, "seg-1"),
    word("am", 0.4, "seg-1"),
    word("not", 0.8, "seg-1"),
    word("in", 1.2, "seg-1"),
    word("danger,", 1.6, "seg-1"),
    word("I", 3.6, "seg-2"),
    word("am", 4.0, "seg-2"),
    word("the", 4.4, "seg-2"),
    word("danger.", 4.8, "seg-2"),
  ],
  emphasisCandidates: [
    {
      text: "danger.",
      startSeconds: 4.8,
      endSeconds: 5.1,
      segmentId: "seg-2",
      reasons: ["louder", "higher_pitch"],
      energyDeltaDb: 4,
      pitchDeltaSemitones: 3,
    },
  ],
};

describe("the script of a recording", () => {
  it("is one line per phrase, in order, with the measured pause after it", () => {
    const lines = buildScript(recording);

    expect(lines.map((line) => line.words.map((item) => item.text).join(" "))).toEqual([
      "I am not in danger,",
      "I am the danger.",
    ]);
    expect(lines.map((line) => line.number)).toEqual([1, 2]);
    expect(lines[0].pauseAfter).toMatchObject({ id: "pause-1", significance: "medium" });
    expect(lines[0].pauseAfter?.durationSeconds).toBeCloseTo(1.6);
    // Nothing follows the last phrase: the silence after it is not a pause.
    expect(lines[1].pauseAfter).toBeNull();
  });

  it("carries each phrase's pace and where to play it from", () => {
    const [first, second] = buildScript(recording);
    expect(first).toMatchObject({ startSeconds: 0, endSeconds: 2, wpm: 150, pace: "faster" });
    expect(second).toMatchObject({ startSeconds: 3.6, endSeconds: 5.5, wpm: 126.3, pace: null });
  });

  it("marks only the word that stood out, not another saying of the same word", () => {
    const lines = buildScript(recording);
    const marked = lines.flatMap((line) => line.words.filter((item) => item.emphasis.length > 0));

    expect(marked).toEqual([{ text: "danger.", emphasis: ["louder", "higher_pitch"] }]);
    // "danger," in the first phrase is the same word, said without standing out.
    expect(lines[0].words.at(-1)).toEqual({ text: "danger,", emphasis: [] });
    expect(scriptCounts(lines)).toEqual({ pauses: 1, marked: 1 });
  });

  it("falls back to a phrase's own text when its words carry no times", () => {
    const lines = buildScript({
      ...recording,
      words: [],
      segments: [segment("seg-1", 0, 2, { transcript: "  मैं खतरा   हूँ " })],
      pauses: [],
    });
    expect(lines[0].words).toEqual([
      { text: "मैं", emphasis: [] },
      { text: "खतरा", emphasis: [] },
      { text: "हूँ", emphasis: [] },
    ]);
  });

  it("is empty-handed, not broken, for a recording in which no words were recognised", () => {
    const lines = buildScript({
      segments: [segment("seg-1", 0, 2)],
      pauses: [],
      words: [],
      emphasisCandidates: [],
    });
    expect(lines).toHaveLength(1);
    expect(lines[0].words).toEqual([]);
    expect(scriptCounts(lines)).toEqual({ pauses: 0, marked: 0 });
  });

  it("says in words why a word stood out", () => {
    expect(emphasisText(["louder"])).toBe("louder");
    expect(emphasisText(["higher_pitch"])).toBe("higher");
    expect(emphasisText(["louder", "higher_pitch"])).toBe("louder and higher");
  });
});
