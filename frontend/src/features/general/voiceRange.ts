/**
 * Small decisions about showing where a voice sits: its pitch and its resonance, each in a
 * lower, neutral or higher range. The measuring and the placing are done by the backend;
 * nothing here works a figure out, apart from where to draw a mark on a scale.
 */
import type {
  SpeechSegment,
  VoiceBand,
  VoiceGoal,
  VoiceMarker,
  VoicePlacement,
  VoiceRange,
} from "./types";

export type VoiceScale = "pitch" | "resonance";

export const BAND_LABEL: Record<VoiceBand, string> = {
  lower: "Lower range",
  neutral: "Neutral range",
  higher: "Higher range",
};

export const MARKER_LABEL: Record<VoiceMarker, string> = {
  lower: "Lower",
  neutral: "Neutral",
  higher: "Higher",
  mixed: "Mixed",
};

/** How a voice in each range is typically heard. About the sound, never about the speaker. */
export const HEARD_AS: Record<VoiceMarker, string> = {
  lower: "Typically heard as a masculine voice.",
  neutral: "Could be heard either way.",
  higher: "Typically heard as a feminine voice.",
  mixed: "Pitch and resonance point different ways, so a listener is given two different cues.",
};

export const GOAL_LABEL: Record<Exclude<VoiceGoal, "none">, string> = {
  lower: "keep your voice in the lower range",
  higher: "keep your voice in the higher range",
};

/** The four values that bound the three ranges of one scale, lowest first. */
export type Edges = { lowEnd: number; neutralFrom: number; neutralTo: number; highEnd: number };

export function edgesOf(bands: Record<string, number>, scale: VoiceScale): Edges | null {
  const edges = {
    lowEnd: bands[`${scale}_low_end_hz`],
    neutralFrom: bands[`${scale}_neutral_from_hz`],
    neutralTo: bands[`${scale}_neutral_to_hz`],
    highEnd: bands[`${scale}_high_end_hz`],
  };
  return Object.values(edges).every((value) => typeof value === "number") ? edges : null;
}

/** "under 145 Hz", "145 to 175 Hz", "over 175 Hz": a range in words. */
export function rangeText(band: VoiceBand, edges: Edges): string {
  if (band === "lower") return `under ${edges.neutralFrom} Hz`;
  if (band === "higher") return `over ${edges.neutralTo} Hz`;
  return `${edges.neutralFrom} to ${edges.neutralTo} Hz`;
}

/**
 * The percentage in words. It is a position inside the range, and the neutral range counts
 * from its edges to its middle, so the two are worded differently.
 */
export function positionText(placement: VoicePlacement): string {
  return placement.band === "neutral"
    ? `${placement.percent}% of the way to its middle`
    : `${placement.percent}% of the way into it`;
}

/**
 * Where a value falls on a bar drawn from the low end of the scale to its high end, as a
 * share of the bar's width. A value beyond either end is drawn at that end.
 */
export function scalePosition(valueHz: number, edges: Edges): number {
  const share = (valueHz - edges.lowEnd) / (edges.highEnd - edges.lowEnd);
  return Math.min(1, Math.max(0, share));
}

/** How wide each of the three ranges is drawn, as shares of the bar that add up to 1. */
export function scaleWidths(edges: Edges): Record<VoiceBand, number> {
  const whole = edges.highEnd - edges.lowEnd;
  return {
    lower: (edges.neutralFrom - edges.lowEnd) / whole,
    neutral: (edges.neutralTo - edges.neutralFrom) / whole,
    higher: (edges.highEnd - edges.neutralTo) / whole,
  };
}

/** True when a phrase was measured and sat somewhere other than the range aimed for. */
export function isOutsideGoal(marker: VoiceMarker | null | undefined, goal: VoiceGoal): boolean {
  return goal !== "none" && marker != null && marker !== goal;
}

/** The phrases that were measured and left the range the speaker is aiming for. */
export function phrasesOutsideGoal(segments: SpeechSegment[], goal: VoiceGoal): SpeechSegment[] {
  return segments.filter((segment) => isOutsideGoal(segment.voice?.marker, goal));
}

/** One sentence on how the recording stands against the goal. Null with no goal. */
export function goalSummary(voice: VoiceRange, segments: SpeechSegment[]): string | null {
  if (voice.goal === "none") return null;
  const measured = segments.filter((segment) => segment.voice?.marker != null);
  if (measured.length === 0) {
    return `Your goal is to ${GOAL_LABEL[voice.goal]}. No phrase could be placed, so there is nothing to set against it.`;
  }
  const outside = phrasesOutsideGoal(segments, voice.goal).length;
  const stayed = measured.length - outside;
  const phrases = measured.length === 1 ? "phrase" : "phrases";
  return `Your goal is to ${GOAL_LABEL[voice.goal]}. ${stayed} of ${measured.length} ${phrases} stayed in it${
    outside === 0 ? "." : `; the ${outside === 1 ? "one that did not is" : `${outside} that did not are`} marked below.`
  }`;
}

/** How the phrases divide between the markers: "5 lower, 2 neutral, 1 mixed". */
export function phraseCountsText(phrases: VoiceRange["phrases"]): string {
  const parts = (["lower", "neutral", "higher", "mixed"] as const)
    .filter((marker) => phrases[marker] > 0)
    .map((marker) => `${phrases[marker]} ${MARKER_LABEL[marker].toLowerCase()}`);
  if (phrases.unmeasured > 0) parts.push(`${phrases.unmeasured} not measured`);
  return parts.join(", ");
}
