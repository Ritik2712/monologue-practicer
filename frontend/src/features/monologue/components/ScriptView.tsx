"use client";

import { formatNumber, formatSpan, formatTimecode } from "@/features/general/format";
import { LinkButton, MUTED } from "@/features/general/components/parts";
import type { AnalysisResult } from "@/features/general/types";
import { useSegmentPlayer } from "@/features/general/useGeneralPractice";

import { buildScript, emphasisText, scriptCounts, type ScriptPause } from "../script";

type ScriptViewProps = {
  /** The original recording's stored result. */
  reference: AnalysisResult;
  /** Where the original can be played from, or null if it is not available. */
  audioSrc: string | null;
};

const PACE_MARK = { faster: "▲ faster", slower: "▼ slower", typical: null } as const;

/**
 * The original as it was delivered, laid out as a script to mark and read from: each
 * phrase on its own line, the measured pause after it, and the words that stood out.
 */
export function ScriptView({ reference, audioSrc }: ScriptViewProps) {
  const { audioProps, playRange } = useSegmentPlayer();
  const lines = buildScript(reference);
  const counts = scriptCounts(lines);

  if (lines.every((line) => line.words.length === 0)) {
    return (
      <p className="text-sm">
        No words were recognised in the original recording, so there is no script to show.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm">
        The original as it was delivered, {formatSpan(reference.durationSeconds)} long:{" "}
        {lines.length} {lines.length === 1 ? "phrase" : "phrases"}, {counts.pauses}{" "}
        {counts.pauses === 1 ? "pause" : "pauses"}
        {counts.marked > 0 &&
          `, and ${counts.marked} ${counts.marked === 1 ? "word that" : "words that"} stood out`}
        .
      </p>

      {/* No controls: it only plays the phrase whose button is pressed. */}
      {audioSrc && <audio {...audioProps} src={audioSrc} preload="metadata" />}

      <ol className="flex flex-col gap-1 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
        {lines.map((line) => (
          <li key={line.segmentId}>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <p className="min-w-0 flex-1 text-base leading-relaxed">
                <span className={`mr-2 text-xs tabular-nums ${MUTED}`}>{line.number}.</span>
                {line.words.map((word, index) => (
                  <span key={index}>
                    {word.emphasis.length > 0 ? (
                      <strong
                        className="font-semibold underline decoration-indigo-600 decoration-2 underline-offset-4 dark:decoration-indigo-400"
                        title={`Stood out: ${emphasisText(word.emphasis)}`}
                      >
                        {word.text}
                        <span className="sr-only"> ({emphasisText(word.emphasis)})</span>
                      </strong>
                    ) : (
                      word.text
                    )}{" "}
                    {word.pausesAfter.map((pause) => (
                      <span
                        key={pause.id}
                        className={`mr-1 text-sm whitespace-nowrap tabular-nums ${MUTED}`}
                      >
                        <span aria-hidden="true" className="text-indigo-700 dark:text-indigo-300">
                          ‖
                        </span>
                        <span className="sr-only">pause </span>
                        {formatNumber(pause.durationSeconds, 1)} s{" "}
                      </span>
                    ))}
                  </span>
                ))}
              </p>
              <p className={`flex items-center gap-x-2 text-xs ${MUTED}`}>
                {line.pace && PACE_MARK[line.pace] && <span>{PACE_MARK[line.pace]}</span>}
                {line.wpm !== null && <span>{formatNumber(line.wpm, 0)} WPM</span>}
                <LinkButton
                  disabled={audioSrc === null}
                  aria-label={`Play phrase ${line.number} of the original`}
                  onClick={() => playRange(line.startSeconds, line.endSeconds)}
                >
                  Play
                </LinkButton>
              </p>
            </div>
            {line.pauseAfter && <PauseMark pause={line.pauseAfter} />}
          </li>
        ))}
      </ol>

      <div className={`text-xs ${MUTED}`}>
        <p>
          <span aria-hidden="true">‖</span> a measured pause, with its length. A pause of
          under a second stays inside its phrase, where it fell; a longer one ends the
          phrase and has a line of its own.{" "}
          <strong className="font-semibold underline decoration-indigo-600 decoration-2 underline-offset-4 dark:decoration-indigo-400">
            Underlined
          </strong>{" "}
          a word that was louder or higher than the speaker&rsquo;s typical word. ▲ ▼ a phrase
          at least a quarter faster or slower than the speaker&rsquo;s own typical pace.
        </p>
        <p className="mt-1">
          The words are what the speech recogniser heard, and emphasis made by slowing down is
          not detected. If words are wrong, correct them under step 1, with “Report a problem”
          on the phrase: the script and every comparison then use the corrected words.
        </p>
      </div>
    </div>
  );
}

function PauseMark({ pause }: { pause: ScriptPause }) {
  const long = pause.significance === "long";
  return (
    <p
      className={`my-1 flex items-center gap-2 text-sm ${
        pause.significance === "short" ? MUTED : "font-medium"
      }`}
    >
      <span aria-hidden="true" className="text-indigo-700 dark:text-indigo-300">
        {long ? "‖‖" : "‖"}
      </span>
      <span>
        {long ? "long silence" : "pause"} {formatNumber(pause.durationSeconds, 1)} s
      </span>
      <span className={`text-xs font-normal ${MUTED}`}>
        at {formatTimecode(pause.startSeconds)}
      </span>
    </p>
  );
}
