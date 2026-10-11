"use client";

import { type ReactNode, useCallback, useId, useState } from "react";

import { Button } from "@/components/Button";

import { PAUSE_CONTEXT_SECONDS } from "../coaching";
import { compareAttempts, earlierAttempts } from "../compare";
import {
  correctionRating,
  labelsChanged,
  madeWithOlderSettings,
  pauseFeedback,
  pauseFloorText,
  revisionLabel,
  segmentFeedback,
  settingsMismatch,
} from "../feedback";
import {
  FLAG_LABELS,
  formatDateTime,
  formatDelta,
  formatMetric,
  formatNumber,
  formatPercent,
  formatSpan,
  formatTimecode,
  languageName,
  PAUSE_LABELS,
  profileName,
  UNAVAILABLE,
} from "../format";
import type { CorrectionState } from "../generalStore";
import type {
  AnalysisResult,
  AnalysisSummary,
  CoachStatus,
  DeliveryProfile,
  MetricName,
  SegmentCorrection,
} from "../types";
import { useSegmentPlayer } from "../useGeneralPractice";
import { Coaching, type Regeneration } from "./Coaching";
import { type FeedbackTools, PauseFeedbackSelect, SegmentReport } from "./FeedbackControls";
import { FeedbackSection } from "./FeedbackSection";
import {
  FOCUS_RING,
  FocusTag,
  LinkButton,
  MUTED,
  Notice,
  QualityBadge,
  Section,
  Tile,
} from "./parts";
import { TimelineChart } from "./TimelineChart";

type ResultsProps = {
  analysis: AnalysisResult;
  /**
   * "take" (the default) shows everything. "reference" is the lighter view for studying a
   * reference recording: its measurements, without coaching or comparisons.
   */
  mode?: "take" | "reference";
  /** The comparison with a reference recording, drawn by the page that owns the references. */
  referenceSection?: ReactNode;
  /** The chosen delivery profile's description, when the options have loaded. */
  profile: DeliveryProfile | undefined;
  history: AnalysisSummary[];
  /** Where the recording can be played from, or null if it is not available. */
  audioSrc: string | null;
  /** Whether the local AI model is available, as the worker last reported. Null if unknown. */
  coach: { status: CoachStatus; model: string | null } | null;
  /** True while an analysis or a coaching job is in progress. */
  busy: boolean;
  /** How the latest request to write this analysis's coaching again is going. */
  regeneration: Regeneration;
  onRegenerateCoaching: () => void;
  onClose: () => void;
  onDelete: () => void;
  onDeleteAudio: () => void;
  /**
   * The feedback on this result and the calibration it feeds. A reference recording takes
   * reports of mistakes in its measurement, but its pauses are not labelled and it has no
   * coaching to rate.
   */
  feedback?: FeedbackTools;
  /** How saving a corrected transcript is going. */
  correction?: CorrectionState;
  onCorrectTranscript?: (corrections: SegmentCorrection[]) => void;
  /** Analyses this result's kept recording again, with the settings in force now. */
  onReanalyse?: () => void;
  /** Opens another result made from the same recording. */
  onOpenRevision?: (analysisId: string) => void;
};

const NO_CORRECTION: CorrectionState = { status: "idle" };

const PACE_LABELS = { typical: "Typical", faster: "Faster", slower: "Slower" } as const;

const SETTING_LABELS: Record<string, [label: string, unit: string]> = {
  version: ["Version of the app's default settings", ""],
  calibration_version: ["Version of your calibration (1 means the defaults)", ""],
  min_pause_ms: ["A silence counts as a pause from", "ms"],
  medium_pause_ms: ["A pause is “medium” from", "ms"],
  long_silence_ms: ["A pause is a “long silence”, starting a new section, from", "ms"],
  min_segment_ms: ["Shortest segment whose WPM is trusted", "ms"],
  min_segment_words: ["Fewest words for a trusted WPM", "words"],
  wpm_outlier: ["A segment is flagged for review above", "WPM"],
  low_confidence: ["Recognition is treated as unsure below a confidence of", ""],
  pace_deviation_ratio: ["“Faster” or “slower” than typical means differing by at least", "(share)"],
  min_segments_for_typical_pace: ["Reliable segments needed for a typical pace", ""],
  vad_threshold: ["Speech probability needed to count as speech", ""],
  vad_min_speech_ms: ["Shorter bursts of speech are ignored", "ms"],
  vad_min_silence_ms: ["Shorter gaps do not split speech", "ms"],
  vad_speech_pad_ms: ["Each speech region is widened by", "ms"],
};

export function Results({
  analysis,
  mode = "take",
  referenceSection,
  profile,
  history,
  audioSrc,
  coach,
  busy,
  regeneration,
  onRegenerateCoaching,
  onClose,
  onDelete,
  onDeleteAudio,
  feedback,
  correction = NO_CORRECTION,
  onCorrectTranscript,
  onReanalyse,
  onOpenRevision,
}: ResultsProps) {
  const { audioProps, playRange, currentTime } = useSegmentPlayer();
  const [showShortPauses, setShowShortPauses] = useState(false);
  const earlier = earlierAttempts(history, analysis.analysisId, analysis.createdAt);
  const [compareId, setCompareId] = useState<string | null>(null);

  const m = analysis.metrics;
  const isReference = mode === "reference";
  const canPlay = audioSrc !== null;
  // The minimum pause this result was made with, in words. Feedback can move it, so it is
  // read from the result rather than assumed to be half a second.
  const pauseFloor = pauseFloorText(analysis.settings);
  const items = feedback?.state.items ?? [];
  const calibration =
    feedback?.state.calibration.status === "ready" ? feedback.state.calibration.data : null;
  const outdated = isReference ? null : madeWithOlderSettings(analysis, calibration);
  const otherRevisions = (analysis.revisions ?? []).filter(
    (item) => item.analysisId !== analysis.analysisId,
  );
  const focus = new Set<MetricName>(profile?.focus.map((item) => item.metric));
  const isFocus = (name: MetricName) => focus.has(name);

  const significantPauses = analysis.pauses.filter((pause) => pause.significance !== "short");
  const shortPauseCount = analysis.pauses.length - significantPauses.length;
  const shownPauses =
    showShortPauses || significantPauses.length === 0 ? analysis.pauses : significantPauses;

  const offPace = analysis.segments.filter(
    (segment) => segment.paceVsTypical === "faster" || segment.paceVsTypical === "slower",
  );
  const baseline = earlier.find((item) => item.analysisId === compareId) ?? earlier[0];
  const language =
    analysis.language.source === "detected" && analysis.language.confidence !== null
      ? `${languageName(analysis.language.code)} (detected, ${
          // Never "100% sure": the recogniser's confidence is not a guarantee.
          analysis.language.confidence >= 0.995
            ? "over 99%"
            : formatPercent(analysis.language.confidence)
        } confidence)`
      : analysis.language.source === "declared"
        ? `${languageName(analysis.language.code)} (as you chose)`
        : languageName(analysis.language.code);

  const playButton = (label: string, start: number, end?: number) => (
    <LinkButton disabled={!canPlay} aria-label={label} onClick={() => playRange(start, end)}>
      Play
    </LinkButton>
  );

  return (
    <section aria-labelledby="results-heading" className="flex flex-col gap-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="results-heading" className="text-xl font-semibold">
            {isReference ? (analysis.title ?? "The reference") : "Results"}
          </h2>
          <p className={`mt-1 text-sm ${MUTED}`}>
            {isReference
              ? "The reference recording, measured the same way as your takes"
              : `${formatDateTime(analysis.createdAt)} · ${profileName(analysis.profile)} profile`}{" "}
            · {language} · {formatSpan(analysis.durationSeconds)}
          </p>
          {(analysis.revision > 1 || otherRevisions.length > 0) && (
            <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm">
              <span className="font-medium">
                {revisionLabel(analysis.revision, analysis.revisionReason)}
              </span>
              <span className={MUTED}>
                {otherRevisions.length > 0
                  ? "Other results from the same recording:"
                  : "The earlier results from this recording were deleted."}
              </span>
              {/* For a reference, opening another revision means comparing with that one. */}
              {onOpenRevision &&
                otherRevisions.map((item) => (
                  <LinkButton key={item.analysisId} onClick={() => onOpenRevision(item.analysisId)}>
                    {revisionLabel(item.revision, item.reason)}
                  </LinkButton>
                ))}
            </p>
          )}
        </div>
        {!isReference && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={onClose}>Close results</Button>
            <Button variant="danger" onClick={onDelete}>
              Delete this analysis
            </Button>
          </div>
        )}
      </header>

      {analysis.warnings.length > 0 && (
        <Notice kind="warning">
          <p className="font-medium">Read these before trusting the numbers</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {analysis.warnings.map((warning) => (
              <li key={warning.code}>{warning.message}</li>
            ))}
          </ul>
        </Notice>
      )}

      {outdated && (
        <Notice kind="info">
          <p>
            This result was made when a silence counted as a pause from {outdated.then} ms. Your
            feedback has since moved that to {outdated.now} ms, so a new analysis of the same
            recording could find different pauses and phrases. This result is not changed.
          </p>
          <p className={`mt-1 ${MUTED}`}>
            {analysis.audioRetained
              ? "Analysing again makes a new revision next to this one, with the settings as they are now."
              : "The recording was not kept, so it cannot be analysed again. Results from new recordings use the new setting."}
          </p>
          {analysis.audioRetained && onReanalyse && (
            <div className="mt-2">
              <Button disabled={busy} onClick={onReanalyse}>
                Analyse this recording again
              </Button>
            </div>
          )}
        </Notice>
      )}

      {/* --- Summary ------------------------------------------------------------------- */}
      <Section id="summary-heading" title="Summary">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <div className="flex flex-wrap items-center gap-2">
              <p className={`text-sm ${MUTED}`}>Speech-active WPM</p>
              <QualityBadge quality={m.speechActiveWpm.quality} />
              {isFocus("speechActiveWpm") && <FocusTag />}
            </div>
            <p className="mt-1 text-5xl font-semibold">{formatMetric(m.speechActiveWpm)}</p>
            <p className={`mt-2 text-sm ${MUTED}`}>
              {m.speechActiveWpm.quality === "unavailable"
                ? m.speechActiveWpm.note
                : "Words ÷ time spent speaking. Pauses are left out, so this is how fast you speak while you are speaking."}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Tile
              label="Whole-clip WPM"
              value={formatMetric(m.wholeClipWpm)}
              metric={m.wholeClipWpm}
              hint="Including pauses: words ÷ the full recording. Not a measure of speaking speed."
            />
            <Tile label="Words" value={formatMetric(m.totalWordCount, 0)} metric={m.totalWordCount} />
            <Tile
              label="Time speaking"
              value={formatMetric(m.speechActiveSeconds)}
              unit="s"
              metric={m.speechActiveSeconds}
              hint={`Of ${formatSpan(analysis.durationSeconds)} recorded.`}
            />
            <Tile
              label="Pauses"
              value={formatMetric(m.pauseCount, 0)}
              metric={m.pauseCount}
              hint={`Silences of ${pauseFloor} or more between phrases.`}
            />
            <Tile
              label="Median pause"
              value={formatMetric(m.medianPauseSeconds, 2)}
              unit="s"
              metric={m.medianPauseSeconds}
              focus={isFocus("medianPauseSeconds")}
              hint="A typical pause: half are shorter, half longer."
            />
            <Tile
              label="Longest pause"
              value={formatMetric(m.longestPauseSeconds, 2)}
              unit="s"
              metric={m.longestPauseSeconds}
              focus={isFocus("longestPauseSeconds")}
            />
          </div>
        </div>
      </Section>

      {/* --- Listen and look ----------------------------------------------------------- */}
      <Section id="recording-heading" title="Recording">
        {canPlay ? (
          <audio
            {...audioProps}
            controls
            src={audioSrc}
            className="w-full"
            aria-label="The recording that was analysed"
          />
        ) : (
          <Notice kind="info">
            The recording for this analysis was not kept, so it cannot be played back. The
            measurements below are complete.
          </Notice>
        )}
        {analysis.audioRetained && (
          <p className={`text-sm ${MUTED}`}>
            This recording is stored on this device.{" "}
            <LinkButton onClick={onDeleteAudio}>Delete the recording, keep the measurements</LinkButton>
          </p>
        )}
        <TimelineChart
          analysis={analysis}
          playheadSeconds={canPlay ? currentTime : null}
          onSeek={canPlay ? (seconds) => playRange(seconds) : undefined}
        />
      </Section>

      {/* --- Coaching ------------------------------------------------------------------ */}
      {/* A reference is someone else's performance: there is nothing to coach it on. */}
      {!isReference && (
        <Coaching
          coaching={analysis.coaching}
          segments={analysis.segments}
          profile={profile}
          coach={coach}
          busy={busy}
          regeneration={regeneration}
          onRegenerate={onRegenerateCoaching}
          playButton={playButton}
          labelsChanged={labelsChanged(analysis.coaching, items)}
          rating={
            feedback && {
              store: feedback.store,
              saving: feedback.state.saving,
              find: (findingId, kind) => correctionRating(items, findingId, kind),
            }
          }
        />
      )}

      {/* --- Against a reference recording ---------------------------------------------- */}
      {!isReference && referenceSection}

      {/* --- Pace ---------------------------------------------------------------------- */}
      <Section
        id="pace-heading"
        title="Pace"
        description={`Each segment is one phrase: speech with no pause of ${pauseFloor} or more inside it. Segment WPM is that phrase's words ÷ its own length.`}
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tile
            label="Your typical pace"
            value={formatMetric(m.typicalSegmentWpm)}
            unit="WPM"
            metric={m.typicalSegmentWpm}
            hint="The median of your reliably measured segments."
          />
          <Tile
            label="Pace variation"
            value={formatMetric(m.paceVariation)}
            unit="WPM"
            metric={m.paceVariation}
            focus={isFocus("paceVariation")}
            hint="How much segment speeds differ. Near 0 means every phrase at the same speed."
          />
          <Tile label="Slowest segment" value={formatMetric(m.paceMinWpm)} unit="WPM" metric={m.paceMinWpm} />
          <Tile label="Fastest segment" value={formatMetric(m.paceMaxWpm)} unit="WPM" metric={m.paceMaxWpm} />
        </div>
        {offPace.length > 0 && (
          <div>
            <p className="text-sm font-medium">Phrases well away from your typical pace</p>
            <ul className="mt-1 flex flex-col gap-1 text-sm">
              {offPace.map((segment) => (
                <li key={segment.id} className="flex flex-wrap items-center gap-x-2">
                  <span>
                    Segment {segment.index + 1} at {formatTimecode(segment.startSeconds)}:{" "}
                    <span className="font-medium">
                      {segment.paceVsTypical} ({formatNumber(segment.segmentWpm)} WPM)
                    </span>
                  </span>
                  {playButton(
                    `Play segment ${segment.index + 1}`,
                    segment.startSeconds,
                    segment.endSeconds,
                  )}
                </li>
              ))}
            </ul>
            <p className={`mt-1 text-xs ${MUTED}`}>
              Compared with your own typical pace in this recording, not with a target. Whether it
              suits the performance is your call.
            </p>
          </div>
        )}
        <SegmentsTable
          analysis={analysis}
          playButton={playButton}
          report={
            feedback && onCorrectTranscript
              ? {
                  tools: feedback,
                  correction,
                  playheadSeconds: canPlay ? currentTime : null,
                  onCorrectTranscript,
                  reference: isReference,
                }
              : undefined
          }
        />
      </Section>

      {/* --- Pauses -------------------------------------------------------------------- */}
      <Section
        id="pauses-heading"
        title="Pauses"
        description="Pauses are measured from the sound. The app does not decide whether a pause was dramatic, accidental or a breath."
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tile
            label="Average pause"
            value={formatMetric(m.averagePauseSeconds, 2)}
            unit="s"
            metric={m.averagePauseSeconds}
          />
          <Tile
            label="Total pause time"
            value={formatMetric(m.totalPauseSeconds)}
            unit="s"
            metric={m.totalPauseSeconds}
          />
          <Tile
            label="Pause share"
            value={formatPercent(m.pauseRatio.value)}
            metric={m.pauseRatio}
            hint="Pause time ÷ recording length."
          >
            {m.pauseRatio.value !== null && (
              <div
                role="meter"
                aria-label="Share of the recording spent in pauses"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(m.pauseRatio.value * 100)}
                className="viz-root mt-2 h-2 overflow-hidden rounded-full bg-[var(--viz-track)]"
              >
                <div
                  className="h-full rounded-full bg-[var(--viz-series-1)]"
                  style={{ width: `${Math.min(100, m.pauseRatio.value * 100)}%` }}
                />
              </div>
            )}
          </Tile>
          <Tile
            label="Silence before / after"
            value={`${formatMetric(m.leadingSilenceSeconds)} / ${formatMetric(m.trailingSilenceSeconds)}`}
            unit="s"
            hint="Before the first word and after the last. Not counted as pauses."
          />
        </div>

        {analysis.pauses.length === 0 ? (
          <p className={`text-sm ${MUTED}`}>No pauses of {pauseFloor} or more were detected.</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Detected pauses</caption>
                <thead className={MUTED}>
                  <tr className="border-b border-zinc-200 dark:border-zinc-800">
                    <th scope="col" className="py-2 pr-4 font-medium">At</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Length</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Kind</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Between</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Listen</th>
                    {feedback && <th scope="col" className="py-2 font-medium">Your feedback</th>}
                  </tr>
                </thead>
                <tbody>
                  {shownPauses.map((pause) => (
                    <tr key={pause.id} className="border-b border-zinc-100 align-top dark:border-zinc-900">
                      <td className="py-2 pr-4 tabular-nums whitespace-nowrap">
                        {formatTimecode(pause.startSeconds)}
                      </td>
                      <td className="py-2 pr-4 tabular-nums whitespace-nowrap">
                        {formatNumber(pause.durationSeconds, 2)} s
                      </td>
                      <td className="py-2 pr-4">
                        {PAUSE_LABELS[pause.significance]}
                        {pause.startsNewSection && (
                          <span className={`block text-xs ${MUTED}`}>Starts a new section</span>
                        )}
                      </td>
                      <td className="py-2 pr-4 whitespace-nowrap">
                        Segments {pause.index + 1} and {pause.index + 2}
                      </td>
                      <td className="py-2 pr-4">
                        {playButton(
                          `Play the pause at ${formatTimecode(pause.startSeconds)} with a little either side`,
                          pause.startSeconds - PAUSE_CONTEXT_SECONDS,
                          pause.endSeconds + PAUSE_CONTEXT_SECONDS,
                        )}
                      </td>
                      {feedback && (
                        <td className="py-2">
                          <PauseFeedbackSelect
                            pause={pause}
                            item={pauseFeedback(items, pause.id)}
                            disabled={feedback.state.saving}
                            store={feedback.store}
                            reference={isReference}
                          />
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {significantPauses.length > 0 && shortPauseCount > 0 && (
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={showShortPauses}
                  onChange={(event) => setShowShortPauses(event.target.checked)}
                  className={`h-4 w-4 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
                />
                Also list the {shortPauseCount} short {shortPauseCount === 1 ? "pause" : "pauses"}{" "}
                (under 1 second)
              </label>
            )}
            {feedback && (
              <p className={`text-xs ${MUTED}`}>
                Your feedback never changes a pause that was measured.{" "}
                {isReference
                  ? "A report that a pause is not one stays on record and counts towards the minimum pause setting; the pause stays in every figure above."
                  : "Calling a pause intentional or accidental changes only how the coaching reads it; the pause stays in every figure above."}{" "}
                To report a pause the app did not detect, use “Report a problem” on its phrase in
                the Pace section.
              </p>
            )}
          </>
        )}
      </Section>

      {/* --- Voice --------------------------------------------------------------------- */}
      <Section
        id="voice-heading"
        title="Voice"
        description="Loudness is relative to this recording only: it depends on the microphone and how close you were, so it cannot be compared between recordings. Pitch is given relative to your own voice; there is no target pitch."
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Tile
            label="Loudness variation"
            value={formatMetric(m.energyVariation)}
            unit="dB"
            metric={m.energyVariation}
            focus={isFocus("energyVariation")}
            hint="Higher means louder and quieter stretches differ more."
          />
          <Tile
            label="Pitch variation"
            value={formatMetric(m.pitchVariationSemitones, 2)}
            unit="semitones"
            metric={m.pitchVariationSemitones}
            focus={isFocus("pitchVariationSemitones")}
            hint="Spread around your own median pitch."
          />
          <Tile
            label="Pitch range"
            value={formatMetric(m.pitchRangeSemitones)}
            unit="semitones"
            metric={m.pitchRangeSemitones}
            hint={m.pitchRangeHz.note ?? undefined}
          />
          <Tile label="Median pitch" value={formatMetric(m.pitchMedianHz, 0)} unit="Hz" metric={m.pitchMedianHz} />
          <Tile
            label="Voice above background"
            value={formatMetric(m.signalToNoise, 0)}
            unit="dB"
            metric={m.signalToNoise}
            hint="Under 10 dB, pauses become hard to detect."
          />
          <Tile
            label="Hesitation sounds"
            value={formatMetric(m.fillerWordCount, 0)}
            metric={m.fillerWordCount}
            hint="“Um”, “uh” and similar. Speech recognition often leaves these out, so the real number may be higher."
          />
          <Tile
            label="Breaths"
            value={formatMetric(m.breathCount, 0)}
            metric={m.breathCount}
          />
        </div>

        <div>
          <p className="text-sm font-medium">Emphasis candidates</p>
          {analysis.emphasisCandidates.length === 0 ? (
            <p className={`mt-1 text-sm ${MUTED}`}>
              No word stood out clearly from your typical loudness or pitch.
            </p>
          ) : (
            <ul className="mt-1 flex flex-col gap-1 text-sm">
              {analysis.emphasisCandidates.map((candidate) => (
                <li key={`${candidate.startSeconds}-${candidate.text}`} className="flex flex-wrap items-center gap-x-2">
                  <span>
                    <span className="font-medium">{candidate.text}</span> at{" "}
                    {formatTimecode(candidate.startSeconds)}:{" "}
                    {candidate.reasons
                      .map((reason) =>
                        reason === "louder"
                          ? `louder (${formatDelta(candidate.energyDeltaDb ?? 0)} dB)`
                          : `higher (${formatDelta(candidate.pitchDeltaSemitones ?? 0)} semitones)`,
                      )
                      .join(", ")}
                  </span>
                  {playButton(
                    `Play the word ${candidate.text}`,
                    candidate.startSeconds - 0.5,
                    candidate.endSeconds + 0.5,
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className={`mt-1 text-xs ${MUTED}`}>
            Candidates only: these words measured louder or higher than your typical word. That
            does not prove they were meant to be stressed, and emphasis by slowing down is not
            detected.
          </p>
        </div>
      </Section>

      {/* --- Feedback ------------------------------------------------------------------ */}
      {feedback && <FeedbackSection analysis={analysis} tools={feedback} reference={isReference} />}

      {/* --- Compare ------------------------------------------------------------------- */}
      {!isReference && (
      <Section
        id="compare-heading"
        title="Compare with an earlier attempt"
        description="Only the change is shown. Whether a change is an improvement depends on what you were going for."
      >
        {baseline ? (
          <>
            <div>
              <label htmlFor="compare-with" className="block text-sm font-medium">
                Earlier attempt
              </label>
              <select
                id="compare-with"
                value={baseline.analysisId}
                onChange={(event) => setCompareId(event.target.value)}
                className={`mt-1 block min-h-11 w-full max-w-md rounded-md border border-zinc-300 bg-white px-3 text-sm dark:border-zinc-700 dark:bg-zinc-900 ${FOCUS_RING}`}
              >
                {earlier.map((item) => (
                  <option key={item.analysisId} value={item.analysisId}>
                    {formatDateTime(item.createdAt)} · {profileName(item.profile)} ·{" "}
                    {formatSpan(item.durationSeconds)}
                    {item.revision > 1 ? ` · revision ${item.revision}` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">This attempt compared with the earlier one</caption>
                <thead className={MUTED}>
                  <tr className="border-b border-zinc-200 dark:border-zinc-800">
                    <th scope="col" className="py-2 pr-4 font-medium">Measurement</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">This attempt</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Earlier</th>
                    <th scope="col" className="py-2 text-right font-medium">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {compareAttempts(m, baseline.metrics).map((row) => {
                    const suffix = row.percent ? "%" : row.unit ? ` ${row.unit}` : "";
                    const show = (value: number | null) =>
                      value === null ? UNAVAILABLE : `${formatNumber(value, row.digits)}${suffix}`;
                    return (
                      <tr key={row.key} className="border-b border-zinc-100 dark:border-zinc-900">
                        <th scope="row" className="py-2 pr-4 font-normal">
                          {row.label}
                          {row.estimated && <span className={`ml-2 text-xs ${MUTED}`}>estimate</span>}
                        </th>
                        <td className="py-2 pr-4 text-right tabular-nums whitespace-nowrap">{show(row.current)}</td>
                        <td className="py-2 pr-4 text-right tabular-nums whitespace-nowrap">{show(row.previous)}</td>
                        <td className="py-2 text-right font-medium tabular-nums whitespace-nowrap">
                          {row.delta === null ? UNAVAILABLE : `${formatDelta(row.delta, row.digits)}${suffix}`}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {settingsMismatch(analysis.settings, baseline.settings) && (
              <Notice kind="warning">{settingsMismatch(analysis.settings, baseline.settings)}</Notice>
            )}
            {baseline.profile !== analysis.profile && (
              <p className={`text-xs ${MUTED}`}>
                The two attempts used different profiles. The measurements are still made the same
                way.
              </p>
            )}
          </>
        ) : (
          <p className={`text-sm ${MUTED}`}>
            There is no earlier attempt yet. Analyse another recording and it can be compared with
            this one.
          </p>
        )}
      </Section>
      )}

      {/* --- Details ------------------------------------------------------------------- */}
      <div className="flex flex-col gap-2">
        {analysis.transcript && (
          <details className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
            <summary className={`cursor-pointer rounded font-medium ${FOCUS_RING}`}>
              {analysis.revisionReason === "transcript_corrected"
                ? "Transcript, with your corrections"
                : "Transcript, as the speech recogniser heard it"}
            </summary>
            <p className="mt-2 text-sm leading-relaxed">{analysis.transcript}</p>
            <p className={`mt-2 text-xs ${MUTED}`}>
              Recognised by the “{analysis.pipeline.speechModel}” model on this device. It can
              mishear words, which changes word counts and WPM.
              {feedback &&
                (isReference
                  ? " To correct a phrase, use “Report a problem” on it in the Pace section: the counts are then worked out again from the corrected words."
                  : " To correct a phrase, use “Report a problem” on it in the Pace section: the counts are then worked out again from your words.")}
            </p>
          </details>
        )}
        <details className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
          <summary className={`cursor-pointer rounded font-medium ${FOCUS_RING}`}>
            Settings that produced these numbers
          </summary>
          <table className="mt-2 w-full text-left text-sm">
            <caption className="sr-only">Analysis settings</caption>
            <tbody>
              {Object.entries(analysis.settings).map(([key, value]) => {
                const [label, unit] = SETTING_LABELS[key] ?? [key, ""];
                return (
                  <tr key={key} className="border-b border-zinc-100 dark:border-zinc-900">
                    <th scope="row" className="py-1.5 pr-4 font-normal">{label}</th>
                    <td className="py-1.5 text-right tabular-nums whitespace-nowrap">
                      {value} {unit}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className={`mt-2 text-xs ${MUTED}`}>
            Speech detection: {analysis.pipeline.voiceActivityDetector}. Pitch:{" "}
            {analysis.pipeline.pitchTracker}. These settings are saved with the result, so it can
            always be explained by the values that were in force.
          </p>
        </details>
      </div>
    </section>
  );
}

type SegmentsTableProps = {
  analysis: AnalysisResult;
  playButton: (label: string, start: number, end?: number) => React.ReactNode;
  /** What reporting a problem with a phrase needs. Left out when feedback cannot be given. */
  report?: {
    tools: FeedbackTools;
    correction: CorrectionState;
    playheadSeconds: number | null;
    onCorrectTranscript: (corrections: SegmentCorrection[]) => void;
    reference?: boolean;
  };
};

function SegmentsTable({ analysis, playButton, report }: SegmentsTableProps) {
  const { segments } = analysis;
  const panelId = useId();
  // One phrase's report form is open at a time, so the table stays readable.
  const [openId, setOpenId] = useState<string | null>(null);
  const openSegment = segments.find((segment) => segment.id === openId);
  // Keyboard and screen-reader users land on the form they have just opened. The function
  // is kept the same between renders so that it runs once, when the form appears, and not
  // every time the page redraws while the recording plays.
  const focusPanel = useCallback((element: HTMLDivElement | null) => {
    element?.focus({ preventScroll: true });
    element?.scrollIntoView({ block: "nearest" });
  }, []);
  if (segments.length === 0) {
    return <p className={`text-sm ${MUTED}`}>No speech was detected, so there are no segments.</p>;
  }
  return (
    <>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <caption className="sr-only">Speech segments</caption>
        <thead className={MUTED}>
          <tr className="border-b border-zinc-200 dark:border-zinc-800">
            <th scope="col" className="py-2 pr-3 font-medium">#</th>
            <th scope="col" className="py-2 pr-3 font-medium">Time</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">Words</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">WPM</th>
            <th scope="col" className="py-2 pr-3 font-medium">Vs. typical</th>
            <th scope="col" className="py-2 pr-3 font-medium">What was said</th>
            <th scope="col" className="py-2 font-medium">{report ? "Listen / report" : "Listen"}</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((segment) => {
            const cautions = segment.flags.map((flag) => FLAG_LABELS[flag] ?? flag);
            const voice = [
              segment.energyDeltaDb !== null && `Loudness ${formatDelta(segment.energyDeltaDb)} dB`,
              segment.pitchDeltaSemitones !== null &&
                `Pitch ${formatDelta(segment.pitchDeltaSemitones)} semitones`,
            ].filter(Boolean);
            const saved = report ? segmentFeedback(report.tools.state.items, segment.id) : [];
            const open = openId === segment.id;
            return (
                <tr
                  key={segment.id}
                  className={`border-b border-zinc-100 align-top dark:border-zinc-900 ${
                    open ? "bg-indigo-50 dark:bg-indigo-950/40" : ""
                  }`}
                >
                  <th scope="row" className="py-2 pr-3 font-normal tabular-nums">
                    {segment.index + 1}
                  </th>
                  <td className="py-2 pr-3 tabular-nums whitespace-nowrap">
                    {formatTimecode(segment.startSeconds)} – {formatTimecode(segment.endSeconds)}
                    <span className={`block text-xs ${MUTED}`}>
                      {formatSpan(segment.speechActiveSeconds)}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {segment.wordCount ?? UNAVAILABLE}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <span className="font-medium tabular-nums">{formatNumber(segment.segmentWpm)}</span>
                    {!segment.reliable && segment.segmentWpm !== null && (
                      <span className="mt-0.5 block">
                        <QualityBadge quality="estimated" />
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    {segment.paceVsTypical ? PACE_LABELS[segment.paceVsTypical] : UNAVAILABLE}
                  </td>
                  <td className="py-2 pr-3">
                    {segment.transcript || <span className={MUTED}>{UNAVAILABLE}</span>}
                    {voice.length > 0 && (
                      <span className={`mt-0.5 block text-xs ${MUTED}`}>
                        Against your typical phrase: {voice.join(" · ")}
                      </span>
                    )}
                    {cautions.length > 0 && (
                      <span className={`mt-0.5 block text-xs ${MUTED}`}>{cautions.join(". ")}.</span>
                    )}
                  </td>
                  <td className="py-2">
                    <div className="flex flex-wrap gap-x-3">
                      {playButton(
                        `Play segment ${segment.index + 1}`,
                        segment.startSeconds,
                        segment.endSeconds,
                      )}
                      {report && (
                        <LinkButton
                          aria-expanded={open}
                          aria-controls={open ? panelId : undefined}
                          aria-label={`${open ? "Close the report on" : "Report a problem with"} segment ${segment.index + 1}`}
                          onClick={() => setOpenId(open ? null : segment.id)}
                        >
                          {open ? "Close" : saved.length > 0 ? `Report (${saved.length} saved)` : "Report a problem"}
                        </LinkButton>
                      )}
                    </div>
                  </td>
                </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    {/* Below the table, not inside it: the table scrolls sideways on a narrow screen, and
        a form should never have to be scrolled sideways to be read. */}
    {report && openSegment && (
      <div
        id={panelId}
        key={openSegment.id}
        tabIndex={-1}
        ref={focusPanel}
        className={`rounded-lg ${FOCUS_RING}`}
      >
        <SegmentReport
          analysis={analysis}
          segment={openSegment}
          saved={segmentFeedback(report.tools.state.items, openSegment.id)}
          tools={report.tools}
          correction={report.correction}
          playheadSeconds={report.playheadSeconds}
          playButton={playButton}
          onCorrectTranscript={report.onCorrectTranscript}
          onClose={() => setOpenId(null)}
          reference={report.reference}
        />
      </div>
    )}
    </>
  );
}
