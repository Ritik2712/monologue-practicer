/**
 * The script of a recording as it was actually delivered: its phrases in order, the
 * measured pause after each, and the words that stood out. It is built from a stored
 * result and adds nothing to it: every pause and every mark is one the analysis measured.
 */
import type {
  AnalysisResult,
  EmphasisCandidate,
  PaceVsTypical,
  PauseSignificance,
} from "@/features/general/types";

export type ScriptWord = {
  text: string;
  /** Why the word stood out from the speaker's typical word. Empty when it did not. */
  emphasis: EmphasisCandidate["reasons"];
};

export type ScriptPause = {
  id: string;
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
  significance: PauseSignificance;
};

export type ScriptLine = {
  segmentId: string;
  /** 1 for the first phrase. */
  number: number;
  startSeconds: number;
  endSeconds: number;
  words: ScriptWord[];
  wpm: number | null;
  /** Faster or slower than the speaker's own typical pace. Null when it could not be judged. */
  pace: PaceVsTypical | null;
  /** The pause between this phrase and the next. Null after the last phrase. */
  pauseAfter: ScriptPause | null;
};

// Word times are stored rounded to the millisecond, so that is what they are matched on.
const at = (segmentId: string | null, startSeconds: number) =>
  `${segmentId ?? ""}@${startSeconds.toFixed(3)}`;

export function buildScript(
  analysis: Pick<AnalysisResult, "segments" | "pauses" | "words" | "emphasisCandidates">,
): ScriptLine[] {
  const emphasis = new Map(
    analysis.emphasisCandidates.map((candidate) => [
      at(candidate.segmentId, candidate.startSeconds),
      candidate.reasons,
    ]),
  );
  const pauseAfter = new Map(analysis.pauses.map((pause) => [pause.afterSegmentId, pause]));

  return analysis.segments.map((segment, index) => {
    const timed = analysis.words.filter((word) => word.segmentId === segment.id);
    const words: ScriptWord[] =
      timed.length > 0
        ? timed.map((word) => ({
            text: word.text,
            emphasis: emphasis.get(at(word.segmentId, word.startSeconds)) ?? [],
          }))
        : // A phrase with no timed words still has its text, if any was recognised.
          (segment.transcript ?? "")
            .split(/\s+/)
            .filter(Boolean)
            .map((text) => ({ text, emphasis: [] }));
    const pause = pauseAfter.get(segment.id);
    return {
      segmentId: segment.id,
      number: index + 1,
      startSeconds: segment.startSeconds,
      endSeconds: segment.endSeconds,
      words,
      wpm: segment.segmentWpm,
      pace: segment.paceVsTypical,
      pauseAfter: pause
        ? {
            id: pause.id,
            startSeconds: pause.startSeconds,
            endSeconds: pause.endSeconds,
            durationSeconds: pause.durationSeconds,
            significance: pause.significance,
          }
        : null,
    };
  });
}

/** How many pauses and marked words the script shows, for the line above it. */
export function scriptCounts(lines: ScriptLine[]): { pauses: number; marked: number } {
  return {
    pauses: lines.filter((line) => line.pauseAfter !== null).length,
    marked: lines.reduce(
      (total, line) => total + line.words.filter((word) => word.emphasis.length > 0).length,
      0,
    ),
  };
}

/** "louder", "higher", or "louder and higher", for a marked word. */
export function emphasisText(reasons: EmphasisCandidate["reasons"]): string {
  return reasons.map((reason) => (reason === "louder" ? "louder" : "higher")).join(" and ");
}
