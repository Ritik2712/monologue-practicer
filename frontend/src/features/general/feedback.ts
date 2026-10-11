/**
 * Small decisions about how feedback and calibration are shown. Kept apart from the
 * components so they can be tested without rendering anything.
 */
import { formatNumber, formatTimecode } from "./format";
import type {
  AnalysisResult,
  Calibration,
  Coaching,
  FeedbackCategory,
  FeedbackItem,
  PauseLabel,
  ShortSilence,
  SpeechSegment,
} from "./types";

/** What can be said about one detected pause. One of these at a time. */
export const PAUSE_CHOICES: { category: FeedbackCategory; label: string }[] = [
  { category: "pause_intentional", label: "Intentional: I meant this pause" },
  { category: "pause_accidental", label: "Accidental: I lost my place" },
  { category: "pause_false", label: "Not a pause: I was still speaking" },
  { category: "split_wrong", label: "Too short to split the phrase here" },
];

/**
 * What can be said about a pause in a reference recording. Only the two reports: a
 * reference has no coaching, so calling its pauses intentional or accidental means nothing.
 */
export const REFERENCE_PAUSE_CHOICES: { category: FeedbackCategory; label: string }[] = [
  { category: "pause_false", label: "Not a pause: someone is still speaking" },
  { category: "split_wrong", label: "Too short to split the phrase here" },
];

const PAUSE_CATEGORIES = new Set(PAUSE_CHOICES.map((choice) => choice.category));

const PAUSE_LABELS: Partial<Record<FeedbackCategory, PauseLabel>> = {
  pause_intentional: "intentional",
  pause_accidental: "accidental",
};

/** The default minimum pause, for results stored before settings recorded it. */
const DEFAULT_MIN_PAUSE_MS = 500;

/** The one piece of feedback given about a pause, if any. */
export function pauseFeedback(items: FeedbackItem[], pauseId: string): FeedbackItem | undefined {
  return items.find((item) => item.targetId === pauseId && PAUSE_CATEGORIES.has(item.category));
}

/** Everything said about one segment: missed pauses, its WPM, its words. */
export function segmentFeedback(items: FeedbackItem[], segmentId: string): FeedbackItem[] {
  return items.filter((item) => item.targetKind === "segment" && item.targetId === segmentId);
}

/**
 * How a correction was rated. The rating is matched on what the correction is about as
 * well as its ID, so a rating never jumps to a different correction after the coaching is
 * written again.
 */
export function correctionRating(
  items: FeedbackItem[],
  findingId: string,
  findingKind: string | undefined,
): FeedbackItem | undefined {
  return items.find(
    (item) =>
      item.targetKind === "correction" &&
      item.targetId === findingId &&
      item.features.finding_kind === findingKind,
  );
}

/** The silences inside a segment that were too short to count as pauses, in order. */
export function silencesIn(analysis: AnalysisResult, segmentId: string): ShortSilence[] {
  return (analysis.shortSilences ?? [])
    .filter((silence) => silence.segmentId === segmentId)
    .sort((a, b) => a.startSeconds - b.startSeconds);
}

/**
 * A recognised word without the punctuation the recogniser attaches to it: "Skyler." is
 * shown as "Skyler". A "word" that is nothing but punctuation is left as it is.
 *
 * Marks (\p{M}) count as part of the word: a Devanagari vowel sign is one, and "रुको"
 * without its last sign is a different word.
 */
export function bareWord(text: string): string {
  return text.replace(/^[^\p{L}\p{N}\p{M}]+|[^\p{L}\p{N}\p{M}]+$/gu, "") || text;
}

/**
 * The last word spoken before a moment in the recording, to say where that moment is.
 * With a segment named, only that phrase's own words are looked at.
 */
export function wordBefore(
  analysis: AnalysisResult,
  seconds: number,
  segmentId?: string | null,
): string | null {
  let found: string | null = null;
  for (const word of analysis.words) {
    if (segmentId && word.segmentId !== segmentId) continue;
    // Half the word must be over: recognised word times overlap silences a little.
    if ((word.startSeconds + word.endSeconds) / 2 <= seconds) found = bareWord(word.text);
  }
  return found;
}

/** A place inside a phrase where a pause could have gone unnoticed: between two words. */
export type WordGap = {
  /** Position of the word before the gap, among the words of the phrase. */
  index: number;
  before: string;
  after: string;
  /** The moment between the two words. */
  atSeconds: number;
};

/**
 * The gaps between the words of a phrase, in order. Picking one is a way of saying where
 * a missed pause was without knowing its time: "after this word".
 */
export function wordGaps(analysis: AnalysisResult, segment: SpeechSegment): WordGap[] {
  const words = analysis.words
    .filter((word) => word.segmentId === segment.id)
    .sort((a, b) => a.startSeconds - b.startSeconds);
  const clamp = (seconds: number) =>
    Math.min(segment.endSeconds, Math.max(segment.startSeconds, seconds));
  return words.slice(0, -1).map((word, index) => ({
    index,
    before: bareWord(word.text),
    after: bareWord(words[index + 1].text),
    atSeconds: clamp((word.endSeconds + words[index + 1].startSeconds) / 2),
  }));
}

/**
 * How far from a marked moment a silence may be and still be taken as the one meant. The
 * backend decides what a report counts for with the same half second
 * (`NEAR_SECONDS` in `backend/app/feedback.py`); this copy only previews its answer.
 */
export const NEAR_SECONDS = 0.5;

/** The silence the backend will take a report at this moment to be about, if any. */
export function silenceNear(silences: ShortSilence[], atSeconds: number): ShortSilence | null {
  const near = silences.filter(
    (silence) =>
      silence.startSeconds - NEAR_SECONDS <= atSeconds &&
      atSeconds <= silence.endSeconds + NEAR_SECONDS,
  );
  const middle = (silence: ShortSilence) => (silence.startSeconds + silence.endSeconds) / 2;
  return near.reduce<ShortSilence | null>(
    (best, silence) =>
      best === null || Math.abs(middle(silence) - atSeconds) < Math.abs(middle(best) - atSeconds)
        ? silence
        : best,
    null,
  );
}

/** The labels now on the pauses, by pause ID. */
export function currentLabels(items: FeedbackItem[]): Record<string, PauseLabel> {
  const labels: Record<string, PauseLabel> = {};
  for (const item of items) {
    const label = PAUSE_LABELS[item.category];
    if (label && item.targetId) labels[item.targetId] = label;
  }
  return labels;
}

/** True when pauses have been labelled, or unlabelled, since the coaching was written. */
export function labelsChanged(coaching: Coaching | null, items: FeedbackItem[]): boolean {
  const used = coaching?.labelsUsed ?? {};
  const now = currentLabels(items);
  const ids = new Set([...Object.keys(used), ...Object.keys(now)]);
  return [...ids].some((id) => used[id] !== now[id]);
}

/** The shortest silence that counted as a pause in a result, in seconds. */
export function minPauseSeconds(settings: Record<string, number> | undefined): number {
  return (settings?.min_pause_ms ?? DEFAULT_MIN_PAUSE_MS) / 1000;
}

/** "half a second" for the default; otherwise the exact figure, e.g. "0.4 seconds". */
export function pauseFloorText(settings: Record<string, number> | undefined): string {
  const seconds = minPauseSeconds(settings);
  if (seconds === 0.5) return "half a second";
  return `${Number(seconds.toFixed(2))} seconds`;
}

/** A setting's value the way the calibration panel writes it: "450 ms", "0.8". */
export function formatSetting(value: number, digits: number, unit: string): string {
  const text = formatNumber(value, digits);
  return unit ? `${text} ${unit}` : text;
}

/**
 * Whether analysing a result's recording again would cut its pauses differently: true
 * when the minimum pause in force now is not the one the result was made with.
 */
export function madeWithOlderSettings(
  analysis: Pick<AnalysisResult, "settings">,
  calibration: Calibration | null,
): { then: number; now: number } | null {
  const current = calibration?.settings.find((setting) => setting.name === "min_pause_ms");
  if (!current) return null;
  const then = analysis.settings.min_pause_ms ?? DEFAULT_MIN_PAUSE_MS;
  return then === current.value ? null : { then, now: current.value };
}

/**
 * Says so when two results were made with a different minimum pause, because their pause
 * counts and phrases are then not like for like. Null when they match.
 */
export function settingsMismatch(
  mine: Record<string, number> | undefined,
  theirs: Record<string, number> | undefined,
): string | null {
  const a = mine?.min_pause_ms ?? DEFAULT_MIN_PAUSE_MS;
  const b = theirs?.min_pause_ms ?? DEFAULT_MIN_PAUSE_MS;
  if (a === b) return null;
  return `The two were analysed with different settings: a silence counted as a pause from ${a} ms in this attempt and from ${b} ms in the earlier one. Pause counts and phrase speeds are therefore not like for like.`;
}

const CATEGORY_TEXT: Record<FeedbackCategory, string> = {
  pause_intentional: "marked intentional",
  pause_accidental: "marked accidental",
  pause_false: "reported as not a pause",
  split_wrong: "reported as too short to split the phrase",
  pause_missed: "a pause was missed",
  wpm_too_high: "the WPM looks too high",
  wpm_too_low: "the WPM looks too low",
  transcript_wrong: "the words are wrong",
  coaching_useful: "rated useful",
  coaching_not_useful: "rated not useful",
};

/** One line saying what a piece of feedback is about, e.g. "Pause at 0:08.6 (3.00 s): marked intentional". */
export function describeFeedback(item: FeedbackItem, analysis: AnalysisResult): string {
  const what = CATEGORY_TEXT[item.category] ?? item.category;
  if (item.targetKind === "pause") {
    const pause = analysis.pauses.find((candidate) => candidate.id === item.targetId);
    return pause
      ? `Pause at ${formatTimecode(pause.startSeconds)} (${formatNumber(pause.durationSeconds, 2)} s): ${what}`
      : `A pause: ${what}`;
  }
  if (item.targetKind === "segment") {
    const segment = analysis.segments.find((candidate) => candidate.id === item.targetId);
    const where = segment ? `Segment ${segment.index + 1}` : "A segment";
    if (item.category === "pause_missed" && item.atSeconds !== null) {
      const before = wordBefore(analysis, item.atSeconds, item.targetId);
      return `${where}: ${what} at ${formatTimecode(item.atSeconds)}${before ? `, after “${before}”` : ""}`;
    }
    return `${where}: ${what}`;
  }
  if (item.targetKind === "correction") {
    const title = item.features.title;
    return typeof title === "string" ? `Correction “${title}”: ${what}` : `A correction: ${what}`;
  }
  return `The whole recording: ${what}`;
}

/** What a kind of revision is called in a list. */
export function revisionLabel(revision: number, reason: string | null | undefined): string {
  if (reason === "transcript_corrected") return `Revision ${revision}: transcript corrected`;
  if (reason === "reanalysed") return `Revision ${revision}: analysed again`;
  return revision === 1 ? "Revision 1: first analysis" : `Revision ${revision}`;
}

/** The line beside the button that asks the AI model: what is happening, or what would. */
export function summaryHint(situation: {
  /** The request is waiting or being answered. */
  working: boolean;
  queued: boolean;
  workerAlive: boolean;
  cancelRequested: boolean;
  /** How many notes the AI model could be offered, and how many it needs. */
  pickableNotes: number;
  minNotes: number;
  /** Why the AI model cannot be asked, in a few words. Null when it can. */
  unavailable: string | null;
}): string {
  if (situation.working) {
    if (situation.cancelRequested) return "Stopping…";
    if (!situation.workerAlive) {
      return "Waiting, because the analysis worker is not running. It will be done once the worker starts.";
    }
    return situation.queued
      ? "Waiting for the worker to finish what it is doing."
      : "The AI model is choosing. This takes a few seconds.";
  }
  if (situation.pickableNotes < situation.minNotes) {
    return `The AI model is asked once there are at least ${situation.minNotes} notes of a few words or more (there ${situation.pickableNotes === 1 ? "is" : "are"} ${situation.pickableNotes}). Until then they are all listed above.`;
  }
  if (situation.unavailable) {
    return `The AI model is not available right now: ${situation.unavailable}. Nothing above depends on it.`;
  }
  return "Optional. The local AI model is given your notes as text and nothing else, and only chooses among them: the words shown are yours. Nothing leaves this computer, and no setting changes.";
}
