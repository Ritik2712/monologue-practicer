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

    expect(marked).toEqual([
      { text: "danger.", emphasis: ["louder", "higher_pitch"], pausesAfter: [] },
    ]);
    // "danger," in the first phrase is the same word, said without standing out.
    expect(lines[0].words.at(-1)).toEqual({ text: "danger,", emphasis: [], pausesAfter: [] });
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
      { text: "मैं", emphasis: [], pausesAfter: [] },
      { text: "खतरा", emphasis: [], pausesAfter: [] },
      { text: "हूँ", emphasis: [], pausesAfter: [] },
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

  it("shows a pause inside a phrase after the word it followed, and the phrase stays one line", () => {
    // "I am not in danger, ‖0.6 s‖ I am the danger." as one phrase, then a second phrase.
    const stretched = (text: string, start: number, stretchIndex: number, segmentId: string) => ({
      ...word(text, start, segmentId),
      stretchIndex,
    });
    const held: ScriptSource = {
      segments: [
        segment("seg-1", 0, 4.5, { segmentWpm: 138.5, deliveryWpm: 120, pauseCount: 1 }),
        segment("seg-2", 6, 8, { segmentWpm: 90, deliveryWpm: 90 }),
      ],
      pauses: [
        { ...pause("pause-1", "seg-1", 2, 2.6, "short"), index: 0, insideSegment: true },
        { ...pause("pause-2", "seg-1", 4.5, 6), index: 1, insideSegment: false },
      ],
      words: [
        stretched("I", 0, 0, "seg-1"),
        stretched("am", 0.4, 0, "seg-1"),
        stretched("not", 0.8, 0, "seg-1"),
        stretched("in", 1.2, 0, "seg-1"),
        stretched("danger,", 1.6, 0, "seg-1"),
        // Timed inside the pause, as the recogniser often times the first word after one.
        stretched("I", 2.3, 1, "seg-1"),
        stretched("am", 3.0, 1, "seg-1"),
        stretched("the", 3.4, 1, "seg-1"),
        stretched("danger.", 3.8, 1, "seg-1"),
        stretched("Remember", 6, 2, "seg-2"),
        stretched("that.", 7, 2, "seg-2"),
      ],
      emphasisCandidates: [],
    };
    const [first, second] = buildScript(held);

    expect(first.words.map((item) => item.text).join(" ")).toBe(
      "I am not in danger, I am the danger.",
    );
    // Only the word before the pause carries it.
    expect(first.words.map((item) => item.pausesAfter.map((mark) => mark.id))).toEqual([
      [], [], [], [], ["pause-1"], [], [], [], [],
    ]);
    expect(first.words[4].pausesAfter[0].durationSeconds).toBeCloseTo(0.6);
    // The pause that ended the phrase is the one after the line, not the one inside it.
    expect(first.pauseAfter?.id).toBe("pause-2");
    expect(second.pauseAfter).toBeNull();
    // The line's pace is its delivery pace, with the pause inside it counted.
    expect(first.wpm).toBe(120);
    expect(scriptCounts([first, second])).toEqual({ pauses: 2, marked: 0 });
  });

  it("says in words why a word stood out", () => {
    expect(emphasisText(["louder"])).toBe("louder");
    expect(emphasisText(["higher_pitch"])).toBe("higher");
    expect(emphasisText(["louder", "higher_pitch"])).toBe("louder and higher");
  });
});
