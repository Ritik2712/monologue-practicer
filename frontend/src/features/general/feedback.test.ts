import { describe, expect, it } from "vitest";

import {
  correctionRating,
  currentLabels,
  describeFeedback,
  formatSetting,
  labelsChanged,
  madeWithOlderSettings,
  minPauseSeconds,
  bareWord,
  PAUSE_CHOICES,
  pauseChoices,
  pauseFeedback,
  pauseFloorText,
  REFERENCE_PAUSE_CHOICES,
  revisionLabel,
  segmentFeedback,
  settingsMismatch,
  silenceNear,
  silencesIn,
  summaryHint,
  wordBefore,
  wordGaps,
} from "./feedback";
import type {
  AnalysisResult,
  Calibration,
  Coaching,
  FeedbackItem,
  ShortSilence,
  SpeechSegment,
} from "./types";

function item(overrides: Partial<FeedbackItem>): FeedbackItem {
  return {
    id: "fb-1",
    analysisId: "analysis-1",
    category: "pause_false",
    targetKind: "pause",
    targetId: "pause-1",
    atSeconds: null,
    note: null,
    createdAt: "2026-10-11T04:00:00Z",
    calibrationVersion: 1,
    features: {},
    effect: "report",
    setting: "min_pause_ms",
    direction: 1,
    message: "Saved.",
    review: null,
    ...overrides,
  };
}

const analysis = {
  settings: { min_pause_ms: 500 },
  pauses: [{ id: "pause-1", startSeconds: 8.6, endSeconds: 11.6, durationSeconds: 3 }],
  segments: [
    { id: "seg-1", index: 0 },
    { id: "seg-2", index: 1 },
  ],
  shortSilences: [
    { startSeconds: 3.0, endSeconds: 3.4, durationSeconds: 0.4, segmentId: "seg-1" },
    { startSeconds: 1.0, endSeconds: 1.2, durationSeconds: 0.2, segmentId: "seg-1" },
    { startSeconds: 6.0, endSeconds: 6.3, durationSeconds: 0.3, segmentId: "seg-2" },
  ],
  words: [
    { text: "you", startSeconds: 0.0, endSeconds: 0.5 },
    { text: "clearly", startSeconds: 0.5, endSeconds: 1.1 },
    { text: "know", startSeconds: 1.2, endSeconds: 1.6 },
  ],
} as unknown as AnalysisResult;

const calibrationAt = (minPause: number) =>
  ({ settings: [{ name: "min_pause_ms", value: minPause }] }) as unknown as Calibration;

describe("finding the feedback that belongs to something", () => {
  const items = [
    item({ id: "label", category: "pause_intentional", targetId: "pause-2" }),
    item({ id: "false", category: "pause_false", targetId: "pause-1" }),
    item({ id: "missed", category: "pause_missed", targetKind: "segment", targetId: "seg-1" }),
    item({ id: "wpm", category: "wpm_too_high", targetKind: "segment", targetId: "seg-1" }),
    item({ id: "whole", category: "wpm_too_low", targetKind: "recording", targetId: null }),
  ];

  it("finds what was said about a pause", () => {
    expect(pauseFeedback(items, "pause-1")?.id).toBe("false");
    expect(pauseFeedback(items, "pause-2")?.id).toBe("label");
    expect(pauseFeedback(items, "pause-3")).toBeUndefined();
  });

  it("lists everything said about a segment, and nothing said about the whole recording", () => {
    expect(segmentFeedback(items, "seg-1").map((entry) => entry.id)).toEqual(["missed", "wpm"]);
    expect(segmentFeedback(items, "seg-2")).toEqual([]);
  });

  it("matches a rating to its correction by what the correction is about", () => {
    const rating = item({
      category: "coaching_not_useful",
      targetKind: "correction",
      targetId: "f3",
      features: { finding_kind: "pace" },
    });

    expect(correctionRating([rating], "f3", "pace")?.category).toBe("coaching_not_useful");
    // After the coaching is rewritten, "f3" may be about something else entirely.
    expect(correctionRating([rating], "f3", "pitch_variation")).toBeUndefined();
    expect(correctionRating([rating], "f4", "pace")).toBeUndefined();
  });
});

describe("what the detector heard inside a phrase", () => {
  it("lists a phrase's short silences in order", () => {
    expect(silencesIn(analysis, "seg-1").map((silence) => silence.startSeconds)).toEqual([1.0, 3.0]);
    expect(silencesIn(analysis, "seg-3")).toEqual([]);
  });

  it("copes with a result stored before short silences were kept", () => {
    expect(silencesIn({ ...analysis, shortSilences: null }, "seg-1")).toEqual([]);
    expect(silencesIn({ ...analysis, shortSilences: undefined }, "seg-1")).toEqual([]);
  });

  it("names the last word spoken before a moment", () => {
    expect(wordBefore(analysis, 1.15)).toBe("clearly");
    expect(wordBefore(analysis, 3.0)).toBe("know");
    expect(wordBefore(analysis, 0.1)).toBeNull();
  });
});

describe("pause labels and the coaching", () => {
  const coaching = (labelsUsed?: Record<string, "intentional" | "accidental">) =>
    ({ labelsUsed }) as unknown as Coaching;
  const intentional = item({ category: "pause_intentional", targetId: "pause-2" });
  const accidental = item({ category: "pause_accidental", targetId: "pause-2" });

  it("reads the labels now on the pauses, ignoring feedback that is not a label", () => {
    expect(currentLabels([intentional, item({ category: "pause_false" })])).toEqual({
      "pause-2": "intentional",
    });
  });

  it("notices a new label, a changed label and a removed label", () => {
    expect(labelsChanged(coaching({}), [intentional])).toBe(true);
    expect(labelsChanged(coaching({ "pause-2": "intentional" }), [accidental])).toBe(true);
    expect(labelsChanged(coaching({ "pause-2": "intentional" }), [])).toBe(true);
  });

  it("sees no change when the coaching already used the same labels", () => {
    expect(labelsChanged(coaching({ "pause-2": "intentional" }), [intentional])).toBe(false);
    expect(labelsChanged(coaching(undefined), [])).toBe(false);
    expect(labelsChanged(null, [item({ category: "pause_false" })])).toBe(false);
  });
});

describe("the minimum pause a result was made with", () => {
  it("is read from the result's own settings, with the default for older results", () => {
    expect(minPauseSeconds({ min_pause_ms: 400 })).toBe(0.4);
    expect(minPauseSeconds({})).toBe(0.5);
    expect(minPauseSeconds(undefined)).toBe(0.5);
  });

  it("is written as half a second only when that is what it is", () => {
    expect(pauseFloorText({ min_pause_ms: 500 })).toBe("half a second");
    expect(pauseFloorText({ min_pause_ms: 400 })).toBe("0.4 seconds");
    expect(pauseFloorText({ min_pause_ms: 350 })).toBe("0.35 seconds");
  });

  it("tells when a result was made before the minimum pause moved", () => {
    expect(madeWithOlderSettings(analysis, calibrationAt(400))).toEqual({ then: 500, now: 400 });
    expect(madeWithOlderSettings(analysis, calibrationAt(500))).toBeNull();
    expect(madeWithOlderSettings(analysis, null)).toBeNull();
  });

  it("warns when two attempts were cut with different minimum pauses", () => {
    expect(settingsMismatch({ min_pause_ms: 400 }, { min_pause_ms: 500 })).toContain(
      "from 400 ms in this attempt and from 500 ms in the earlier one",
    );
    expect(settingsMismatch({ min_pause_ms: 500 }, {})).toBeNull();
    expect(settingsMismatch(undefined, undefined)).toBeNull();
    // The same minimum pause, but one result keeps short pauses inside its phrases.
    const cut = settingsMismatch(
      { min_pause_ms: 500, segment_break_ms: 1000 },
      { min_pause_ms: 500 },
    );
    expect(cut).toContain("this attempt ended a phrase only at a pause of 1 s or more");
    expect(cut).toContain("the earlier one at every pause");
    expect(
      settingsMismatch(
        { min_pause_ms: 500, segment_break_ms: 1000 },
        { min_pause_ms: 500, segment_break_ms: 1000 },
      ),
    ).toBeNull();
  });
});

describe("wording", () => {
  it("writes a setting with its unit", () => {
    expect(formatSetting(450, 0, "ms")).toBe("450 ms");
    expect(formatSetting(0.8, 1, "")).toBe("0.8");
  });

  it("says what a piece of feedback is about", () => {
    expect(describeFeedback(item({ category: "pause_intentional" }), analysis)).toBe(
      "Pause at 0:08.6 (3.00 s): marked intentional",
    );
    expect(
      describeFeedback(
        item({ category: "pause_missed", targetKind: "segment", targetId: "seg-2", atSeconds: 6.1 }),
        analysis,
      ),
    ).toBe("Segment 2: a pause was missed at 0:06.1");
    expect(
      describeFeedback(
        item({ category: "wpm_too_high", targetKind: "recording", targetId: null }),
        analysis,
      ),
    ).toBe("The whole recording: the WPM looks too high");
    expect(
      describeFeedback(
        item({
          category: "coaching_not_useful",
          targetKind: "correction",
          targetId: "f3",
          features: { title: "Slow your overall pace" },
        }),
        analysis,
      ),
    ).toBe("Correction “Slow your overall pace”: rated not useful");
  });

  it("says which word a missed pause came after, looking only at that phrase", () => {
    const spoken = {
      ...analysis,
      words: [
        { text: "the", startSeconds: 5.0, endSeconds: 5.4, segmentId: "seg-1" },
        { text: "market", startSeconds: 5.5, endSeconds: 6.0, segmentId: "seg-2" },
        { text: "today", startSeconds: 6.4, endSeconds: 6.9, segmentId: "seg-2" },
      ],
    } as unknown as AnalysisResult;
    const missed = (atSeconds: number) =>
      item({ category: "pause_missed", targetKind: "segment", targetId: "seg-2", atSeconds });

    expect(describeFeedback(missed(6.2), spoken)).toBe(
      "Segment 2: a pause was missed at 0:06.2, after “market”",
    );
    // Before the phrase's first word is over there is no word to name: not "the".
    expect(describeFeedback(missed(5.6), spoken)).toBe("Segment 2: a pause was missed at 0:05.6");
  });

  it("still says something for a target the result no longer has", () => {
    expect(describeFeedback(item({ targetId: "pause-9" }), analysis)).toBe(
      "A pause: reported as not a pause",
    );
  });

  it("names each kind of revision", () => {
    expect(revisionLabel(1, null)).toBe("Revision 1: first analysis");
    expect(revisionLabel(2, "transcript_corrected")).toBe("Revision 2: transcript corrected");
    expect(revisionLabel(3, "reanalysed")).toBe("Revision 3: analysed again");
  });
});

describe("saying where a missed pause was by picking a word", () => {
  const phrase = { id: "seg-2", startSeconds: 4.0, endSeconds: 8.0 } as SpeechSegment;
  const spoken = {
    words: [
      { text: "elsewhere", startSeconds: 1.0, endSeconds: 1.5, segmentId: "seg-1" },
      // Out of order on purpose: the gaps follow the time, not the list.
      { text: "home", startSeconds: 7.0, endSeconds: 7.6, segmentId: "seg-2" },
      { text: "going", startSeconds: 4.1, endSeconds: 4.6, segmentId: "seg-2" },
      { text: "to", startSeconds: 4.6, endSeconds: 4.8, segmentId: "seg-2" },
      { text: "market", startSeconds: 4.8, endSeconds: 5.4, segmentId: "seg-2" },
    ],
  } as unknown as AnalysisResult;

  it("lists the gap after every word but the last, each at the moment between two words", () => {
    expect(wordGaps(spoken, phrase)).toEqual([
      { index: 0, before: "going", after: "to", atSeconds: 4.6 },
      { index: 1, before: "to", after: "market", atSeconds: 4.8 },
      { index: 2, before: "market", after: "home", atSeconds: 6.2 },
    ]);
  });

  it("shows a word without the punctuation the recogniser attaches to it", () => {
    expect(bareWord("Skyler.")).toBe("Skyler");
    expect(bareWord("“No,”")).toBe("No");
    expect(bareWord("don't")).toBe("don't");
    expect(bareWord("रुको,")).toBe("रुको");
    // Nothing but punctuation: better shown as it is than as nothing.
    expect(bareWord("...")).toBe("...");
    const punctuated = {
      words: [
        { text: "danger,", startSeconds: 4.1, endSeconds: 4.6, segmentId: "seg-2" },
        { text: "Skyler.", startSeconds: 4.7, endSeconds: 5.2, segmentId: "seg-2" },
      ],
    } as unknown as AnalysisResult;
    expect(wordGaps(punctuated, phrase)[0]).toMatchObject({ before: "danger", after: "Skyler" });
    expect(wordBefore(punctuated, 5.0, "seg-2")).toBe("Skyler");
  });

  it("has no gap to offer in a phrase of one word, or of none", () => {
    expect(wordGaps(spoken, { id: "seg-1", startSeconds: 0, endSeconds: 2 } as SpeechSegment)).toEqual([]);
    expect(wordGaps(spoken, { id: "seg-9", startSeconds: 0, endSeconds: 2 } as SpeechSegment)).toEqual([]);
  });

  it("keeps a gap inside the phrase when the recogniser's word times stray out of it", () => {
    const strayed = {
      words: [
        { text: "so", startSeconds: 3.2, endSeconds: 3.4, segmentId: "seg-2" },
        { text: "then", startSeconds: 3.5, endSeconds: 3.9, segmentId: "seg-2" },
      ],
    } as unknown as AnalysisResult;
    expect(wordGaps(strayed, phrase)[0].atSeconds).toBe(4.0);
  });

  const silence = (startSeconds: number, endSeconds: number) =>
    ({ startSeconds, endSeconds, durationSeconds: endSeconds - startSeconds, segmentId: "seg-2" }) as ShortSilence;

  it("previews the silence a report will be about: the nearest within half a second", () => {
    const silences = [silence(5.5, 5.9), silence(6.3, 6.5)];
    expect(silenceNear(silences, 6.2)).toBe(silences[1]);
    expect(silenceNear(silences, 5.6)).toBe(silences[0]);
    // Half a second either side still counts; any further does not.
    expect(silenceNear(silences, 5.0)).toBe(silences[0]);
    expect(silenceNear(silences, 4.9)).toBeNull();
    expect(silenceNear([], 6.2)).toBeNull();
  });
});

describe("feedback on a reference recording", () => {
  it("offers the two reports about a pause, and neither label", () => {
    expect(REFERENCE_PAUSE_CHOICES.map((choice) => choice.category)).toEqual([
      "pause_false",
      "split_wrong",
    ]);
    expect(PAUSE_CHOICES.map((choice) => choice.category)).toContain("pause_intentional");
  });
});

describe("what can be said about one pause", () => {
  const categories = (
    pause: { insideSegment?: boolean },
    options: { reference: boolean; holdsPauses: boolean },
  ) => pauseChoices(pause, options).map((choice) => choice.category);

  it("is the full list in a result whose phrases end at every pause", () => {
    expect(pauseChoices({}, { reference: false, holdsPauses: false })).toEqual(PAUSE_CHOICES);
    expect(pauseChoices({}, { reference: true, holdsPauses: false })).toEqual(
      REFERENCE_PAUSE_CHOICES,
    );
  });

  it("leaves out “split the phrase” for a pause that is inside its phrase", () => {
    const inside = { insideSegment: true };
    expect(categories(inside, { reference: false, holdsPauses: true })).toEqual([
      "pause_intentional",
      "pause_accidental",
      "pause_false",
    ]);
    expect(categories(inside, { reference: true, holdsPauses: true })).toEqual(["pause_false"]);
  });

  it("words it as ending the phrase for a pause that did end one", () => {
    const choices = pauseChoices({ insideSegment: false }, { reference: false, holdsPauses: true });
    expect(choices.map((choice) => choice.category)).toContain("split_wrong");
    expect(choices.find((choice) => choice.category === "split_wrong")?.label).toBe(
      "Should not have ended the phrase",
    );
  });
});

describe("the line beside the button that asks the AI model to pick notes", () => {
  const idle = {
    working: false,
    queued: false,
    workerAlive: true,
    cancelRequested: false,
    pickableNotes: 8,
    minNotes: 5,
    unavailable: null,
  };

  it("says what the model would be given, and that it only chooses", () => {
    expect(summaryHint(idle)).toContain("is given your notes as text and nothing else");
    expect(summaryHint(idle)).toContain("the words shown are yours");
    expect(summaryHint(idle)).toContain("no setting changes");
  });

  it("says why the model cannot be asked", () => {
    expect(summaryHint({ ...idle, pickableNotes: 2 })).toContain(
      "at least 5 notes of a few words or more (there are 2)",
    );
    expect(summaryHint({ ...idle, pickableNotes: 1 })).toContain("(there is 1)");
    expect(summaryHint({ ...idle, unavailable: "Ollama is not running" })).toContain(
      "not available right now: Ollama is not running",
    );
  });

  it("follows a request that is waiting or being answered", () => {
    const working = { ...idle, working: true };
    expect(summaryHint({ ...working, queued: true })).toBe(
      "Waiting for the worker to finish what it is doing.",
    );
    expect(summaryHint(working)).toContain("The AI model is choosing");
    expect(summaryHint({ ...working, queued: true, workerAlive: false })).toContain(
      "the analysis worker is not running",
    );
    expect(summaryHint({ ...working, cancelRequested: true })).toBe("Stopping…");
  });
});
