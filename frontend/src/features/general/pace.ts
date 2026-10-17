/**
 * Small decisions about showing pace, and the pauses a phrase holds.
 *
 * A phrase (segment) ends at a pause long enough to end it. A shorter pause stays inside
 * its phrase. So a phrase has two paces: its delivery pace, over its whole length with
 * those pauses counted, and its speaking speed, over the time spent speaking only. Both
 * are worked out by the backend; nothing here works a figure out.
 *
 * A result made before phrases could hold a pause has one pace per phrase, and every
 * function here reads it as that phrase's delivery pace, which is exactly what it is.
 */
import type { AnalysisResult, MetricValue, Metrics, PauseEvent, SpeechSegment } from "./types";

/** False for a result made before a phrase could hold a pause. */
export function hasDeliveryPace(analysis: Pick<AnalysisResult, "stretches">): boolean {
  return analysis.stretches != null;
}

export function deliveryWpmOf(segment: SpeechSegment): number | null {
  return segment.deliveryWpm ?? segment.segmentWpm;
}

/** The recording's delivery pace, whichever kind of result it is from. */
export function recordingDelivery(
  metrics: Pick<Metrics, "deliveryWpm" | "speechActiveWpm">,
): MetricValue {
  return metrics.deliveryWpm ?? metrics.speechActiveWpm;
}

/** The same for a history row, which carries only some of the metrics. */
export function summaryDelivery(metrics: {
  deliveryWpm?: MetricValue | null;
  speechActiveWpm?: MetricValue;
}): MetricValue | undefined {
  return metrics.deliveryWpm ?? metrics.speechActiveWpm;
}

/** How long a pause must be to end a phrase in this result, in seconds. */
export function segmentBreakSeconds(analysis: Pick<AnalysisResult, "settings">): number {
  const settings = analysis.settings;
  if (typeof settings.segment_break_ms === "number") return settings.segment_break_ms / 1000;
  // Before the setting existed, every pause ended a phrase.
  return (settings.min_pause_ms ?? 500) / 1000;
}

/** "1 second", "0.4 seconds": a length in words, for a sentence. */
export function secondsText(seconds: number): string {
  const shown = Number(seconds.toFixed(2));
  return `${shown} ${shown === 1 ? "second" : "seconds"}`;
}

/** The pauses a phrase holds, in order. */
export function pausesInside(analysis: Pick<AnalysisResult, "pauses">, segmentId: string): PauseEvent[] {
  return analysis.pauses.filter(
    (pause) => pause.insideSegment === true && pause.afterSegmentId === segmentId,
  );
}

/** One unbroken run of words in a phrase, and the pause that follows it inside the phrase. */
export type PhrasePart = {
  text: string;
  startSeconds: number;
  endSeconds: number;
  pauseAfter: PauseEvent | null;
};

/**
 * A phrase as its runs of words with the pauses between them, for showing where in the
 * line each pause fell. Which side of a pause a word is on comes from the stretch the
 * backend put it in, never from the word's own time, which can stray into the pause.
 */
export function phraseParts(
  analysis: Pick<AnalysisResult, "stretches" | "pauses" | "words">,
  segment: SpeechSegment,
): PhrasePart[] {
  const whole: PhrasePart[] = [
    {
      text: segment.transcript ?? "",
      startSeconds: segment.startSeconds,
      endSeconds: segment.endSeconds,
      pauseAfter: null,
    },
  ];
  const stretches = (analysis.stretches ?? []).filter((stretch) => stretch.segmentId === segment.id);
  if (stretches.length < 2) return whole;
  const parts = stretches.map((stretch, position) => ({
    text: analysis.words
      .filter((word) => word.stretchIndex === stretch.index)
      .map((word) => word.text)
      .join(" "),
    startSeconds: stretch.startSeconds,
    endSeconds: stretch.endSeconds,
    pauseAfter:
      position < stretches.length - 1
        ? (analysis.pauses.find((pause) => pause.index === stretch.index) ?? null)
        : null,
  }));
  // With no words recognised there is nothing to place the pauses among.
  return parts.some((part) => part.text) ? parts : whole;
}

/** Where a pause lies: "Inside phrase 3" or "Between phrases 3 and 4". */
export function pausePlace(
  analysis: Pick<AnalysisResult, "segments">,
  pause: PauseEvent,
): string {
  const numberOf = (id: string) => {
    const segment = analysis.segments.find((item) => item.id === id);
    return segment ? segment.index + 1 : null;
  };
  const after = numberOf(pause.afterSegmentId) ?? pause.index + 1;
  if (pause.insideSegment) return `Inside phrase ${after}`;
  return `Between phrases ${after} and ${numberOf(pause.beforeSegmentId) ?? after + 1}`;
}

/** "2 pauses, 1.4 s": what a phrase holds, or null when it holds none. */
export function insidePausesText(segment: SpeechSegment): string | null {
  const count = segment.pauseCount ?? 0;
  if (count === 0) return null;
  const seconds = Number((segment.pauseSeconds ?? 0).toFixed(1));
  return `${count} ${count === 1 ? "pause" : "pauses"} inside, ${seconds} s`;
}

/** True for a result with speech in it that was cut when every pause ended a phrase. */
export function madeBeforeSegmentBreak(
  analysis: Pick<AnalysisResult, "stretches" | "segments">,
): boolean {
  return analysis.stretches == null && analysis.segments.length > 0;
}
