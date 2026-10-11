"use client";

import { Button } from "@/components/Button";
import { LinkButton, MUTED, Notice } from "@/features/general/components/parts";
import type { ComparisonState } from "@/features/general/generalStore";
import type { PlayRange } from "@/features/general/types";
import { useSegmentPlayer } from "@/features/general/useGeneralPractice";

/** The checklist asks for the two biggest things to change, so that is how many are shown. */
export const DIFFERENCES_TO_CORRECT = 2;

type CorrectToolsProps = {
  /** The take on view set against the original. */
  comparison: ComparisonState;
  /** True when a take of this monologue is on view. */
  hasTake: boolean;
  takeAudioSrc: string | null;
  referenceAudioSrc: string | null;
  /** Takes the user back to step 4 with a clean recorder. */
  onRecordAgain: () => void;
};

/**
 * Step 5: the biggest differences between the take on view and the original, each with
 * both versions to listen to, and the way back to recording another take.
 */
export function CorrectTools({
  comparison,
  hasTake,
  takeAudioSrc,
  referenceAudioSrc,
  onRecordAgain,
}: CorrectToolsProps) {
  const takePlayer = useSegmentPlayer();
  const referencePlayer = useSegmentPlayer();
  const play = (player: typeof takePlayer, range: PlayRange | null) =>
    range && player.playRange(range.startSeconds, range.endSeconds);

  const again = (
    <div>
      <Button onClick={onRecordAgain}>{hasTake ? "Record another take" : "Go to recording"}</Button>
    </div>
  );

  if (!hasTake) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm">
          No take is on view. Record one in step 4, or open one of your earlier takes there
          with “Compare”, and its biggest differences from the original are listed here.
        </p>
        {again}
      </div>
    );
  }

  const differences =
    comparison.status === "ready"
      ? comparison.data.differences.slice(0, DIFFERENCES_TO_CORRECT)
      : [];

  return (
    <div className="flex flex-col gap-3">
      {comparison.status === "loading" && <p className={`text-sm ${MUTED}`}>Comparing…</p>}
      {comparison.status === "error" && (
        <Notice kind="error">The comparison could not be made. {comparison.message}</Notice>
      )}
      {comparison.status === "ready" && differences.length === 0 && (
        <p className="text-sm">
          {comparison.data.alignment.status === "matched" ||
          comparison.data.alignment.status === "partial"
            ? "No difference in pauses or pace was large enough to list. The tables in step 4 have every figure."
            : comparison.data.alignment.note}
        </p>
      )}
      {differences.length > 0 && (
        <>
          {/* No controls: they only play the spot whose button is pressed. */}
          {referenceAudioSrc && (
            <audio {...referencePlayer.audioProps} src={referenceAudioSrc} preload="metadata" />
          )}
          {takeAudioSrc && <audio {...takePlayer.audioProps} src={takeAudioSrc} preload="metadata" />}
          <ol className="flex flex-col gap-2">
            {differences.map((difference, index) => (
              <li
                key={difference.statement}
                className="rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-800"
              >
                <p>
                  <span className={MUTED}>{index + 1}.</span> {difference.statement}
                </p>
                {(difference.referencePlay || difference.takePlay) && (
                  <div className="mt-1 flex flex-wrap items-center gap-x-2">
                    <span className={`text-xs ${MUTED}`}>Listen:</span>
                    <LinkButton
                      disabled={referenceAudioSrc === null || difference.referencePlay === null}
                      aria-label={`Play the original at difference ${index + 1}`}
                      onClick={() => play(referencePlayer, difference.referencePlay)}
                    >
                      Original
                    </LinkButton>
                    <LinkButton
                      disabled={takeAudioSrc === null || difference.takePlay === null}
                      aria-label={`Play your take at difference ${index + 1}`}
                      onClick={() => play(takePlayer, difference.takePlay)}
                    >
                      Yours
                    </LinkButton>
                  </div>
                )}
              </li>
            ))}
          </ol>
          <p className={`text-xs ${MUTED}`}>
            The {differences.length === 1 ? "largest difference" : "two largest differences"}{" "}
            measured, in pauses and pace. Differences, not mistakes: whether to follow the
            original at each point is your decision. A recording that was not kept cannot be
            played.
          </p>
        </>
      )}
      {again}
    </div>
  );
}
