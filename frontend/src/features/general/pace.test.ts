import { describe, expect, it } from "vitest";

import {
  deliveryWpmOf,
  hasDeliveryPace,
  insidePausesText,
  madeBeforeSegmentBreak,
  pausePlace,
  pausesInside,
  phraseParts,
  recordingDelivery,
  secondsText,
  segmentBreakSeconds,
  summaryDelivery,
} from "./pace";
import type { AnalysisResult, MetricValue, PauseEvent, SpeechSegment, WordTiming } from "./types";

const metric = (value: number | null): MetricValue => ({
  value,
  unit: "words/minute",
  quality: "measured",
  note: null,
});
const segment = (index: number, fields: Partial<SpeechSegment> = {}) =>
  ({
    id: `seg-${index + 1}`,
    index,
    startSeconds: 0,
    endSeconds: 5,
    transcript: "you clearly do not know who you are talking to",
    segmentWpm: 136.4,
    ...fields,
  }) as SpeechSegment;
const pause = (index: number, after: number, before: number, seconds = 0.6): PauseEvent => ({
  id: `pause-${index + 1}`,
  index,
  startSeconds: 2,
  endSeconds: 2 + seconds,
  durationSeconds: seconds,
  significance: "short",
  afterSegmentId: `seg-${after + 1}`,
  beforeSegmentId: `seg-${before + 1}`,
  insideSegment: after === before,
  startsNewSection: false,
});
const words = (text: string, stretchIndex: number, segmentId: string): WordTiming[] =>
  text.split(" ").map((word) => ({
    text: word,
    startSeconds: 0,
    endSeconds: 0,
    confidence: 0.9,
    segmentId,
    stretchIndex,
  }));

// One line holding a 0.6 s pause, a 1.5 s pause, then a second line.
const NEW = {
  settings: { version: 3, min_pause_ms: 500, segment_break_ms: 1000 },
  segments: [
    segment(0, { deliveryWpm: 120, pauseCount: 1, pauseSeconds: 0.6 }),
    segment(1, { startSeconds: 6.5, endSeconds: 10.5, transcript: "so let me clue you in", deliveryWpm: 165, segmentWpm: 165, pauseCount: 0, pauseSeconds: 0 }),
  ],
  stretches: [
    { index: 0, startSeconds: 0, endSeconds: 2, segmentId: "seg-1" },
    { index: 1, startSeconds: 2.6, endSeconds: 5, segmentId: "seg-1" },
    { index: 2, startSeconds: 6.5, endSeconds: 10.5, segmentId: "seg-2" },
  ],
  pauses: [pause(0, 0, 0), pause(1, 0, 1, 1.5)],
  words: [
    ...words("you clearly do not know", 0, "seg-1"),
    ...words("who you are talking to", 1, "seg-1"),
    ...words("so let me clue you in", 2, "seg-2"),
  ],
} as unknown as AnalysisResult;

// The same recording as it was stored before a phrase could hold a pause.
const OLD = {
  settings: { version: 2, min_pause_ms: 500 },
  segments: [segment(0, { segmentWpm: 150 }), segment(1, { segmentWpm: 144 })],
  pauses: [{ ...pause(0, 0, 1), insideSegment: undefined }],
  words: [],
} as unknown as AnalysisResult;

describe("which pace a result has", () => {
  it("is the delivery pace where one is stored", () => {
    expect(hasDeliveryPace(NEW)).toBe(true);
    expect(deliveryWpmOf(NEW.segments[0])).toBe(120);
    expect(recordingDelivery({ deliveryWpm: metric(140), speechActiveWpm: metric(150) }).value).toBe(140);
    expect(summaryDelivery({ deliveryWpm: metric(140), speechActiveWpm: metric(150) })?.value).toBe(140);
  });

  it("is the one pace an older result has, which is its delivery pace", () => {
    expect(hasDeliveryPace(OLD)).toBe(false);
    expect(deliveryWpmOf(OLD.segments[0])).toBe(150);
    expect(recordingDelivery({ speechActiveWpm: metric(150) }).value).toBe(150);
    expect(recordingDelivery({ deliveryWpm: null, speechActiveWpm: metric(150) }).value).toBe(150);
    expect(summaryDelivery({ speechActiveWpm: metric(150) })?.value).toBe(150);
    expect(summaryDelivery({})).toBeUndefined();
  });
});

describe("the pause that ends a phrase", () => {
  it("is read from the result", () => {
    expect(segmentBreakSeconds(NEW)).toBe(1);
    expect(secondsText(segmentBreakSeconds(NEW))).toBe("1 second");
  });

  it("was every pause in an older result, so it is that result's minimum pause", () => {
    expect(segmentBreakSeconds(OLD)).toBe(0.5);
    expect(secondsText(0.5)).toBe("0.5 seconds");
    expect(madeBeforeSegmentBreak(OLD)).toBe(true);
    expect(madeBeforeSegmentBreak(NEW)).toBe(false);
    // Nothing to say about a recording with no speech in it.
    expect(madeBeforeSegmentBreak({ stretches: null, segments: [] })).toBe(false);
  });
});

describe("the pauses a phrase holds", () => {
  it("are the ones inside it, not the one that ended it", () => {
    expect(pausesInside(NEW, "seg-1").map((item) => item.id)).toEqual(["pause-1"]);
    expect(pausesInside(NEW, "seg-2")).toEqual([]);
    expect(pausesInside(OLD, "seg-1")).toEqual([]);
  });

  it("are summed up in a few words, or not mentioned when there are none", () => {
    expect(insidePausesText(NEW.segments[0])).toBe("1 pause inside, 0.6 s");
    expect(insidePausesText(segment(0, { pauseCount: 2, pauseSeconds: 1.45 }))).toBe(
      "2 pauses inside, 1.4 s",
    );
    expect(insidePausesText(NEW.segments[1])).toBeNull();
    expect(insidePausesText(OLD.segments[0])).toBeNull();
  });

  it("are placed by the phrases around them", () => {
    expect(pausePlace(NEW, NEW.pauses[0])).toBe("Inside phrase 1");
    expect(pausePlace(NEW, NEW.pauses[1])).toBe("Between phrases 1 and 2");
    expect(pausePlace(OLD, OLD.pauses[0])).toBe("Between phrases 1 and 2");
  });
});

describe("a phrase as runs of words with its pauses between them", () => {
  it("puts each pause after the words that came before it", () => {
    const parts = phraseParts(NEW, NEW.segments[0]);
    expect(parts.map((part) => part.text)).toEqual([
      "you clearly do not know",
      "who you are talking to",
    ]);
    expect(parts.map((part) => part.pauseAfter?.id ?? null)).toEqual(["pause-1", null]);
    expect([parts[0].startSeconds, parts[1].endSeconds]).toEqual([0, 5]);
  });

  it("never shows the pause that ended the phrase as being inside it", () => {
    const [only] = phraseParts(NEW, NEW.segments[1]);
    expect(only.text).toBe("so let me clue you in");
    expect(only.pauseAfter).toBeNull();
  });

  it("goes by the stretch a word was put in, not by the word's own time", () => {
    // The first word after the pause is timed inside it, as the recogniser often does.
    const strayed = {
      ...NEW,
      words: NEW.words.map((word, position) =>
        position === 5 ? { ...word, startSeconds: 2.1, endSeconds: 2.5 } : word,
      ),
    } as AnalysisResult;
    expect(phraseParts(strayed, strayed.segments[0])[1].text).toBe("who you are talking to");
  });

  it("is the whole phrase in one piece for an older result", () => {
    const parts = phraseParts(OLD, OLD.segments[0]);
    expect(parts).toHaveLength(1);
    expect(parts[0].text).toBe("you clearly do not know who you are talking to");
    expect(parts[0].pauseAfter).toBeNull();
  });

  it("falls back to the whole phrase when no words were recognised", () => {
    const wordless = { ...NEW, words: [] } as unknown as AnalysisResult;
    expect(phraseParts(wordless, NEW.segments[0])).toHaveLength(1);
  });
});
