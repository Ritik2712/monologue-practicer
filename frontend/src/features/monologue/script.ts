/**
 * The script of a recording as it was actually delivered: its phrases in order, the
 * measured pauses inside and after each, and the words that stood out. It is built from a
 * stored result and adds nothing to it: every pause and every mark is one the analysis
 * measured.
 */
import { deliveryWpmOf } from "@/features/general/pace";
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
  /** A pause inside the phrase that came straight after this word. Usually none. */
  pausesAfter: ScriptPause[];
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
  /** The phrase's delivery pace: its words over its whole length, pauses inside counted. */
  wpm: number | null;
  /** Faster or slower than the speaker's own typical pace. Null when it could not be judged. */
  pace: PaceVsTypical | null;
  /** The pause that ended this phrase. Null after the last phrase. */
  pauseAfter: ScriptPause | null;
};

const scriptPause = (pause: AnalysisResult["pauses"][number]): ScriptPause => ({
  id: pause.id,
  startSeconds: pause.startSeconds,
  endSeconds: pause.endSeconds,
  durationSeconds: pause.durationSeconds,
  significance: pause.significance,
});

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
  const pauseAfter = new Map(
    analysis.pauses
      .filter((pause) => !pause.insideSegment)
      .map((pause) => [pause.afterSegmentId, pause]),
  );
  // Pause n lies between stretch n and stretch n + 1.
  const inside = new Map(
    analysis.pauses.filter((pause) => pause.insideSegment).map((pause) => [pause.index, pause]),
  );
  /** The pauses inside a phrase that fall between two neighbouring words of it. */
  const between = (from: number | null | undefined, to: number | null | undefined) => {
    const found: ScriptPause[] = [];
    if (from == null || to == null) return found;
    for (let index = from; index < to; index += 1) {
      const pause = inside.get(index);
      if (pause) found.push(scriptPause(pause));
    }
    return found;
  };

  return analysis.segments.map((segment, index) => {
    const timed = analysis.words.filter((word) => word.segmentId === segment.id);
    const words: ScriptWord[] =
      timed.length > 0
        ? timed.map((word, position) => ({
            text: word.text,
            emphasis: emphasis.get(at(word.segmentId, word.startSeconds)) ?? [],
            // Which side of a pause a word is on comes from its stretch, not its time.
            pausesAfter: between(word.stretchIndex, timed[position + 1]?.stretchIndex),
          }))
        : // A phrase with no timed words still has its text, if any was recognised.
          (segment.transcript ?? "")
            .split(/\s+/)
            .filter(Boolean)
            .map((text) => ({ text, emphasis: [], pausesAfter: [] }));
    const pause = pauseAfter.get(segment.id);
    return {
      segmentId: segment.id,
      number: index + 1,
      startSeconds: segment.startSeconds,
      endSeconds: segment.endSeconds,
      words,
      wpm: deliveryWpmOf(segment),
      pace: segment.paceVsTypical,
      pauseAfter: pause ? scriptPause(pause) : null,
    };
  });
}

/** How many pauses and marked words the script shows, for the line above it. */
export function scriptCounts(lines: ScriptLine[]): { pauses: number; marked: number } {
  return {
    pauses: lines.reduce(
      (total, line) =>
        total +
        (line.pauseAfter ? 1 : 0) +
        line.words.reduce((inside, word) => inside + word.pausesAfter.length, 0),
      0,
    ),
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
