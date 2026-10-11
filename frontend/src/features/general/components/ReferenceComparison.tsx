"use client";

import { useState } from "react";

import { formatDelta, formatNumber, formatSpan, formatTimecode, UNAVAILABLE } from "../format";
import type { ComparisonState, WaveformState } from "../generalStore";
import type { AnalysisSummary, ComparedPause, ComparedPhrase, PlayRange } from "../types";
import { useSegmentPlayer } from "../useGeneralPractice";
import { FOCUS_RING, LinkButton, MUTED, Notice } from "./parts";
import { WaveformComparison } from "./WaveformComparison";

type ReferenceComparisonProps = {
  comparison: ComparisonState;
  /** The chosen reference, from the list. */
  reference: AnalysisSummary;
  takeId: string;
  /** Where each recording can be played from, or null if it is not available. */
  takeAudioSrc: string | null;
  referenceAudioSrc: string | null;
  waveforms: Record<string, WaveformState>;
  onLoadWaveform: (analysisId: string) => void;
};

/**
 * One of your takes set against a reference recording: the biggest differences, then pause
 * by pause and phrase by phrase, each with both versions to listen to.
 */
export function ReferenceComparison({
  comparison,
  reference,
  takeId,
  takeAudioSrc,
  referenceAudioSrc,
  waveforms,
  onLoadWaveform,
}: ReferenceComparisonProps) {
  const takePlayer = useSegmentPlayer();
  const referencePlayer = useSegmentPlayer();
  // Off until asked for: the waveforms are not even fetched before then.
  const [showWaveforms, setShowWaveforms] = useState(false);
  const title = reference.title ?? "Reference";

  const toggleWaveforms = (show: boolean) => {
    setShowWaveforms(show);
    if (show) {
      onLoadWaveform(takeId);
      onLoadWaveform(reference.analysisId);
    }
  };

  const listen = (range: PlayRange | null, takeRange: PlayRange | null, what: string) => (
    <span className="flex flex-wrap gap-x-2">
      <LinkButton
        disabled={referenceAudioSrc === null || range === null}
        aria-label={`Play the reference ${what}`}
        onClick={() => range && referencePlayer.playRange(range.startSeconds, range.endSeconds)}
      >
        Reference
      </LinkButton>
      <LinkButton
        disabled={takeAudioSrc === null || takeRange === null}
        aria-label={`Play your take ${what}`}
        onClick={() => takeRange && takePlayer.playRange(takeRange.startSeconds, takeRange.endSeconds)}
      >
        Yours
      </LinkButton>
    </span>
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <Player label={`Reference: ${title}`} src={referenceAudioSrc} audioProps={referencePlayer.audioProps} />
        <Player label="Your take" src={takeAudioSrc} audioProps={takePlayer.audioProps} />
      </div>

      {comparison.status === "loading" && <p className={`text-sm ${MUTED}`}>Comparing…</p>}
      {comparison.status === "error" && (
        <Notice kind="error">The comparison could not be made. {comparison.message}</Notice>
      )}

      {comparison.status === "ready" && (
        <>
          <Notice kind={comparison.data.alignment.status === "matched" ? "info" : "warning"}>
            {comparison.data.alignment.note}
          </Notice>
          {comparison.data.settingsNote && (
            <Notice kind="warning">{comparison.data.settingsNote}</Notice>
          )}

          {comparison.data.differences.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold">Biggest differences from the reference</h4>
              <ol className="mt-2 flex flex-col gap-2">
                {comparison.data.differences.map((difference, index) => (
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
                        {listen(difference.referencePlay, difference.takePlay, "here")}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
              <p className={`mt-1 text-xs ${MUTED}`}>
                Differences, not mistakes. Whether to follow the reference at each point is your
                decision.
              </p>
            </div>
          )}
          {comparison.data.differences.length === 0 &&
            comparison.data.alignment.status !== "unmatched" &&
            comparison.data.alignment.status !== "no_words" && (
              <p className="text-sm">
                No difference in pauses or pace was large enough to list. The tables below have
                every figure.
              </p>
            )}

          {comparison.data.pauses.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold">Pause by pause</h4>
              <div className="mt-1 overflow-x-auto">
                <table className="w-full min-w-[34rem] text-left text-sm">
                  <caption className="sr-only">
                    Each pause in the reference and in your take, at the same place in the words
                  </caption>
                  <thead className={MUTED}>
                    <tr className="border-b border-zinc-200 dark:border-zinc-800">
                      <th scope="col" className="py-2 pr-3 font-medium">After the words</th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">Reference</th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">Yours</th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">Difference</th>
                      <th scope="col" className="py-2 font-medium">Listen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.data.pauses.map((pause) => (
                      <PauseRow
                        key={`${pause.reference?.pauseId}-${pause.take?.pauseId}`}
                        pause={pause}
                        listen={listen}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {comparison.data.phrases.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold">Phrase by phrase</h4>
              <p className={`mt-1 text-xs ${MUTED}`}>
                Each phrase of the reference, and the pace at which the same words are said in
                your take. Pauses inside the phrase are left out of both. An estimate: it rests
                on the recognised words and their times.
              </p>
              <div className="mt-1 overflow-x-auto">
                <table className="w-full min-w-[36rem] text-left text-sm">
                  <caption className="sr-only">
                    The pace of each phrase in the reference and in your take
                  </caption>
                  <thead className={MUTED}>
                    <tr className="border-b border-zinc-200 dark:border-zinc-800">
                      <th scope="col" className="py-2 pr-3 font-medium">Phrase, as the reference says it</th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">Reference WPM</th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">Your WPM</th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">Difference</th>
                      <th scope="col" className="py-2 font-medium">Listen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.data.phrases.map((phrase) => (
                      <PhraseRow key={phrase.referenceSegmentId} phrase={phrase} listen={listen} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div>
            <h4 className="text-sm font-semibold">The recordings as wholes</h4>
            <div className="mt-1 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Your take and the reference, measurement by measurement</caption>
                <thead className={MUTED}>
                  <tr className="border-b border-zinc-200 dark:border-zinc-800">
                    <th scope="col" className="py-2 pr-4 font-medium">Measurement</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Yours</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Reference</th>
                    <th scope="col" className="py-2 text-right font-medium">Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.data.metrics.map((row) => {
                    const suffix = row.unit === "%" ? "%" : row.unit ? ` ${row.unit}` : "";
                    const show = (value: number | null) =>
                      value === null ? UNAVAILABLE : `${formatNumber(value, row.digits)}${suffix}`;
                    return (
                      <tr key={row.metric} className="border-b border-zinc-100 dark:border-zinc-900">
                        <th scope="row" className="py-2 pr-4 font-normal">
                          {row.label}
                          {row.estimated && <span className={`ml-2 text-xs ${MUTED}`}>estimate</span>}
                          {row.note && <span className={`block text-xs ${MUTED}`}>{row.note}</span>}
                        </th>
                        <td className="py-2 pr-4 text-right tabular-nums whitespace-nowrap">{show(row.take)}</td>
                        <td className="py-2 pr-4 text-right tabular-nums whitespace-nowrap">{show(row.reference)}</td>
                        <td className="py-2 text-right font-medium tabular-nums whitespace-nowrap">
                          {row.difference === null
                            ? UNAVAILABLE
                            : `${formatDelta(row.difference, row.digits)}${suffix}`}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className={`mt-1 text-xs ${MUTED}`}>
              Both recordings were measured in the same way. If your take covers more or less of
              the text than the reference, the totals differ for that reason alone.
            </p>
          </div>

          <details className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
            <summary className={`cursor-pointer rounded text-sm font-medium ${FOCUS_RING}`}>
              What this comparison does not tell you
            </summary>
            <ul className={`mt-2 list-disc space-y-1 pl-5 text-sm ${MUTED}`}>
              {comparison.data.caveats.map((caveat) => (
                <li key={caveat}>{caveat}</li>
              ))}
            </ul>
          </details>
        </>
      )}

      <div className="flex flex-col gap-3">
        <label className="flex cursor-pointer items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={showWaveforms}
            onChange={(event) => toggleWaveforms(event.target.checked)}
            className={`mt-0.5 h-4 w-4 shrink-0 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
          />
          <span>
            Show waveform comparison (visual only)
            <span className={`block text-xs ${MUTED}`}>
              Draws both sound waves on one timeline. It is a picture: no measurement on this
              page comes from it, and switching it on or off changes nothing else.
            </span>
          </span>
        </label>
        {showWaveforms && (
          <WaveformComparison
            reference={waveforms[reference.analysisId]}
            take={waveforms[takeId]}
            referenceLabel={title}
          />
        )}
      </div>
    </div>
  );
}

type AudioProps = ReturnType<typeof useSegmentPlayer>["audioProps"];

function Player({ label, src, audioProps }: { label: string; src: string | null; audioProps: AudioProps }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-sm font-medium">{label}</p>
      {src ? (
        <audio {...audioProps} controls src={src} className="mt-1 w-full" aria-label={label} />
      ) : (
        <p className={`mt-1 text-xs ${MUTED}`}>
          This recording was not kept, so it cannot be played. Its measurements are complete.
        </p>
      )}
    </div>
  );
}

type Listen = (range: PlayRange | null, takeRange: PlayRange | null, what: string) => React.ReactNode;

function PauseRow({ pause, listen }: { pause: ComparedPause; listen: Listen }) {
  const seconds = (value: number) => `${formatNumber(value, 2)} s`;
  const reference =
    pause.reference !== null ? (
      <>
        {seconds(pause.reference.durationSeconds)}
        <span className={`block text-xs ${MUTED}`}>at {formatTimecode(pause.reference.startSeconds)}</span>
      </>
    ) : (
      "No pause"
    );
  const take =
    pause.take !== null ? (
      <>
        {seconds(pause.take.durationSeconds)}
        <span className={`block text-xs ${MUTED}`}>at {formatTimecode(pause.take.startSeconds)}</span>
      </>
    ) : pause.status === "unplaced" ? (
      <span className={MUTED}>Not found in your take</span>
    ) : (
      "No pause"
    );
  return (
    <tr className="border-b border-zinc-100 align-top dark:border-zinc-900">
      <th scope="row" className="py-2 pr-3 font-normal">“{pause.afterWords}”</th>
      <td className="py-2 pr-3 text-right tabular-nums whitespace-nowrap">{reference}</td>
      <td className="py-2 pr-3 text-right tabular-nums whitespace-nowrap">{take}</td>
      <td className="py-2 pr-3 text-right font-medium tabular-nums whitespace-nowrap">
        {pause.differenceSeconds === null
          ? UNAVAILABLE
          : `${formatDelta(pause.differenceSeconds, 2)} s`}
      </td>
      <td className="py-2">{listen(pause.referencePlay, pause.takePlay, `around “${pause.afterWords}”`)}</td>
    </tr>
  );
}

function PhraseRow({ phrase, listen }: { phrase: ComparedPhrase; listen: Listen }) {
  const reason =
    phrase.takePlay === null
      ? "Not found in your take"
      : phrase.coverage < 0.6
        ? "Too few of its words were found in your take to compare pace"
        : "Too short to compare pace";
  return (
    <tr className="border-b border-zinc-100 align-top dark:border-zinc-900">
      <th scope="row" className="py-2 pr-3 font-normal">
        {phrase.text || <span className={MUTED}>{UNAVAILABLE}</span>}
        <span className={`block text-xs ${MUTED}`}>
          {formatTimecode(phrase.referencePlay.startSeconds)} in the reference
          {phrase.takePlay && `, ${formatTimecode(phrase.takePlay.startSeconds)} in yours`}
          {!phrase.comparable && `. ${reason}.`}
        </span>
      </th>
      <td className="py-2 pr-3 text-right tabular-nums">{formatNumber(phrase.referenceWpm)}</td>
      <td className="py-2 pr-3 text-right tabular-nums">{formatNumber(phrase.takeWpm)}</td>
      <td className="py-2 pr-3 text-right font-medium tabular-nums whitespace-nowrap">
        {phrase.differenceWpm === null || phrase.differenceRatio === null ? (
          UNAVAILABLE
        ) : (
          <>
            {formatDelta(phrase.differenceWpm)}
            <span className={`block text-xs font-normal ${MUTED}`}>
              {formatDelta(phrase.differenceRatio * 100, 0)}%
            </span>
          </>
        )}
      </td>
      <td className="py-2">{listen(phrase.referencePlay, phrase.takePlay, "saying this phrase")}</td>
    </tr>
  );
}

/** A one-line description of a reference for lists and menus. */
export function describeReference(reference: AnalysisSummary): string {
  return `${reference.title ?? "Reference"} · ${formatSpan(reference.durationSeconds)}`;
}
