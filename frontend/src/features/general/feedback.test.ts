import { describe, expect, it } from "vitest";

import {
  correctionRating,
  currentLabels,
  describeFeedback,
  formatSetting,
  labelsChanged,
  madeWithOlderSettings,
  minPauseSeconds,
  pauseFeedback,
  pauseFloorText,
  revisionLabel,
  segmentFeedback,
  settingsMismatch,
  silencesIn,
  wordBefore,
} from "./feedback";
import type { AnalysisResult, Calibration, Coaching, FeedbackItem } from "./types";

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
