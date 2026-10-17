"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { audioSourceFor } from "@/features/general/coaching";
import { FOCUS_RING, LinkButton, MUTED, Notice, Tile } from "@/features/general/components/parts";
import { ReferenceComparison } from "@/features/general/components/ReferenceComparison";
import { RunPanel } from "@/features/general/components/RunPanel";
import {
  AudioPicker,
  OptionsRow,
  type AudioSource,
  type ChosenFile,
} from "@/features/general/components/SetupForm";
import { revisionLabel } from "@/features/general/feedback";
import { formatDateTime, formatMetric, formatSpan } from "@/features/general/format";
import { hasDeliveryPace, recordingDelivery, summaryDelivery } from "@/features/general/pace";
import type { GeneralState, GeneralStore } from "@/features/general/generalStore";
import type { AnalysisResult, LanguageHint } from "@/features/general/types";
import { generalApi, useRecorder } from "@/features/general/useGeneralPractice";
import { validateAudioFile } from "@/features/general/validation";

import { takeHref } from "../links";

type RecordToolsProps = {
  state: GeneralState;
  store: GeneralStore;
  monologue: { id: string; title: string };
  /** The language the original was spoken in, as the starting choice for a take. */
  language: string | null;
  /** The take of this monologue that is on view, if any. */
  take: AnalysisResult | null;
  /** The original recording's stored result. Null while it is loading. */
  reference: AnalysisResult | null;
};

function recordingFilename(extension: string): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `take-${stamp}${extension}`;
}

const SPOKEN: readonly LanguageHint[] = ["en", "hi", "hinglish"];

/**
 * Step 4: record or upload a take of this monologue, have it analysed, and see where it
 * differs from the original. Earlier takes of the same monologue are listed underneath.
 */
export function RecordTools({ state, store, monologue, language, take, reference }: RecordToolsProps) {
  const { state: recorderState, recorder } = useRecorder();
  // A take is most likely in the language of the original, which also lines up best with it.
  const [spoken, setSpoken] = useState<LanguageHint>(
    SPOKEN.find((code) => code === language) ?? "auto",
  );
  const [retainAudio, setRetainAudio] = useState(false);
  const [source, setSource] = useState<AudioSource>("record");
  const [chosenFile, setChosenFile] = useState<ChosenFile | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  // Addresses of audio that an analysis now depends on: these must not be released.
  const submittedUrls = useRef(new Set<string>());

  const options = state.options.status === "ready" ? state.options.data : null;
  const busy = ["submitting", "tracking", "loading_result"].includes(state.run.phase);
  const takes = state.takes.monologueId === monologue.id ? state.takes : null;

  const release = (url: string | null | undefined) => {
    if (url && !submittedUrls.current.has(url)) URL.revokeObjectURL(url);
  };

  const chooseFile = (file: File | null) => {
    release(chosenFile?.url);
    setFileError(null);
    if (!file || !options) {
      setChosenFile(null);
      return;
    }
    const check = validateAudioFile(file, options.limits);
    if (!check.ok) {
      setChosenFile(null);
      setFileError(check.message);
      return;
    }
    setChosenFile({ file, url: URL.createObjectURL(file) });
  };

  const discardRecording = () => {
    if (recorderState.status === "recorded") release(recorderState.recording.url);
    recorder.discard();
  };

  const audio =
    source === "record"
      ? recorderState.status === "recorded"
        ? {
            blob: recorderState.recording.blob,
            filename: recordingFilename(recorderState.recording.extension),
            url: recorderState.recording.url,
          }
        : null
      : chosenFile
        ? { blob: chosenFile.file, filename: chosenFile.file.name, url: chosenFile.url }
        : null;

  const analyse = () => {
    if (!audio || busy) return;
    if (audio.url) submittedUrls.current.add(audio.url);
    store.submit({
      audio: audio.blob,
      filename: audio.filename,
      // A take of a monologue is set against its original, not against a delivery profile.
      profile: "custom",
      language: spoken,
      retainAudio,
      monologueId: monologue.id,
      voiceGoal: state.voiceGoal,
      previewUrl: audio.url,
    });
  };

  return (
    <div className="flex flex-col gap-6">
      {state.options.status === "loading" && <p className={MUTED}>Loading…</p>}
      {state.options.status === "error" && (
        <Notice kind="error" action={<Button onClick={() => store.loadOptions()}>Try again</Button>}>
          The form could not be loaded. {state.options.message}
        </Notice>
      )}
      {options && (
        <div className="flex flex-col gap-4">
          <AudioPicker
            title="Your take"
            limits={options.limits}
            source={source}
            onSourceChange={setSource}
            recorderState={recorderState}
            recorder={recorder}
            onDiscardRecording={discardRecording}
            chosenFile={chosenFile}
            fileError={fileError}
            onFileChosen={chooseFile}
          />
          <OptionsRow
            options={options}
            language={spoken}
            onLanguageChange={setSpoken}
            retainAudio={retainAudio}
            onRetainAudioChange={setRetainAudio}
            voiceGoal={state.voiceGoal}
            onVoiceGoalChange={(goal) => store.setVoiceGoal(goal)}
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" disabled={!audio || busy} onClick={analyse}>
              Analyse and compare
            </Button>
            <p className={`text-sm ${MUTED}`}>
              {busy
                ? "A run is already in progress."
                : !audio
                  ? source === "record"
                    ? "Record something first."
                    : "Choose a file first."
                  : `It will be compared with the original of “${monologue.title}”, and saved under this monologue. The step timer does not have to be running.`}
            </p>
          </div>
        </div>
      )}

      {state.runRole === "take" && (
        <RunPanel
          run={state.run}
          kind={state.runKind}
          role={state.runRole}
          coachingFor={state.coachingFor}
          again={state.reanalysisFor !== null}
          store={store}
        />
      )}

      {state.viewed.status === "loading" && <p className={`text-sm ${MUTED}`}>Loading that take…</p>}
      {state.viewed.status === "error" && (
        <Notice kind="error" action={<Button onClick={() => store.closeAnalysis()}>Dismiss</Button>}>
          That take could not be opened. {state.viewed.message}
        </Notice>
      )}

      {take && (
        <section aria-labelledby="take-comparison-heading" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 id="take-comparison-heading" className="text-lg font-semibold">
                Your take against the original
              </h3>
              <p className={`mt-1 text-sm ${MUTED}`}>
                Take of {formatDateTime(take.createdAt)} · {formatSpan(take.durationSeconds)}
                {take.revision > 1 && ` · ${revisionLabel(take.revision, take.revisionReason)}`}
              </p>
            </div>
            <Button onClick={() => store.closeAnalysis()}>Close this take</Button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile
              label="Delivery pace"
              value={formatMetric(recordingDelivery(take.metrics))}
              unit="WPM"
              metric={recordingDelivery(take.metrics)}
              hint={
                hasDeliveryPace(take)
                  ? "Words ÷ the length of your phrases. Short pauses inside a phrase are counted."
                  : "Words ÷ time speaking. Pauses are left out."
              }
            />
            <Tile
              label="Pauses"
              value={formatMetric(take.metrics.pauseCount, 0)}
              metric={take.metrics.pauseCount}
            />
            <Tile
              label="Median pause"
              value={formatMetric(take.metrics.medianPauseSeconds, 2)}
              unit="s"
              metric={take.metrics.medianPauseSeconds}
            />
            <Tile
              label="Longest pause"
              value={formatMetric(take.metrics.longestPauseSeconds, 2)}
              unit="s"
              metric={take.metrics.longestPauseSeconds}
            />
          </div>

          {reference ? (
            <ReferenceComparison
              // Fresh players and a closed waveform for each pair of recordings.
              key={`${take.analysisId}-${reference.analysisId}`}
              comparison={state.comparison}
              reference={reference}
              takeId={take.analysisId}
              takeAudioSrc={audioSourceFor(take, state.localAudio, generalApi)}
              referenceAudioSrc={audioSourceFor(reference, state.localAudio, generalApi)}
              waveforms={state.waveforms}
              onLoadWaveform={(analysisId) => store.loadWaveform(analysisId)}
            />
          ) : (
            <p className={`text-sm ${MUTED}`}>Loading the original recording…</p>
          )}

          <p className="text-sm">
            <Link
              href={takeHref(take.analysisId)}
              className={`rounded font-medium text-indigo-800 underline underline-offset-4 hover:no-underline dark:text-indigo-300 ${FOCUS_RING}`}
            >
              Full analysis of this take: every measurement, the coaching, and feedback on them
            </Link>
          </p>
        </section>
      )}

      <section aria-labelledby="takes-heading" className="flex flex-col gap-2">
        <h3 id="takes-heading" className="text-lg font-semibold">
          Your takes of this monologue
        </h3>
        {(!takes || takes.status === "loading") && <p className={`text-sm ${MUTED}`}>Loading…</p>}
        {takes?.status === "error" && (
          <Notice kind="error">The takes could not be loaded. {takes.message}</Notice>
        )}
        {takes?.status === "ready" && takes.items.length === 0 && (
          <p className={`text-sm ${MUTED}`}>
            None yet. Each take you analyse here is saved under this monologue, on this device,
            and can be opened again on any day.
          </p>
        )}
        {takes && takes.items.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[34rem] text-left text-sm">
                <caption className="sr-only">Your takes of this monologue, newest first</caption>
                <thead className={MUTED}>
                  <tr className="border-b border-zinc-200 dark:border-zinc-800">
                    <th scope="col" className="py-2 pr-3 font-medium">When</th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">Length</th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">Delivery pace (WPM)</th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">Pauses</th>
                    <th scope="col" className="py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {takes.items.map((item) => {
                    const when = formatDateTime(item.createdAt);
                    const showing = item.analysisId === take?.analysisId;
                    return (
                      <tr
                        key={item.analysisId}
                        className={`border-b border-zinc-100 align-top dark:border-zinc-900 ${
                          showing ? "bg-indigo-50 dark:bg-indigo-950/40" : ""
                        }`}
                      >
                        <th scope="row" className="py-2 pr-3 font-normal">
                          <span className="whitespace-nowrap">{when}</span>
                          {item.revision > 1 && (
                            <span className="block text-xs font-medium">
                              {revisionLabel(item.revision, item.revisionReason)}
                            </span>
                          )}
                          {item.audioRetained && (
                            <span className={`block text-xs ${MUTED}`}>Recording kept</span>
                          )}
                        </th>
                        <td className="py-2 pr-3 text-right tabular-nums whitespace-nowrap">
                          {formatSpan(item.durationSeconds)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {formatMetric(summaryDelivery(item.metrics))}
                          {summaryDelivery(item.metrics)?.quality === "estimated" && (
                            <span className={`block text-xs ${MUTED}`}>estimate</span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {formatMetric(item.metrics.pauseCount, 0)}
                        </td>
                        <td className="py-2">
                          <div className="flex flex-wrap items-center gap-x-3">
                            <LinkButton
                              aria-label={`Compare the take from ${when} with the original`}
                              aria-current={showing ? "true" : undefined}
                              onClick={() => store.openAnalysis(item.analysisId)}
                            >
                              {showing ? "Showing" : "Compare"}
                            </LinkButton>
                            <Link
                              href={takeHref(item.analysisId)}
                              aria-label={`Full analysis of the take from ${when}`}
                              className={`rounded px-1 py-1.5 text-sm font-medium text-indigo-800 underline underline-offset-4 hover:no-underline dark:text-indigo-300 ${FOCUS_RING}`}
                            >
                              Full analysis
                            </Link>
                            <LinkButton
                              aria-label={`Delete the take from ${when}`}
                              onClick={() => setDeleting(item.analysisId)}
                            >
                              Delete
                            </LinkButton>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {takes.total > takes.items.length && (
              <p className={`text-sm ${MUTED}`}>
                Showing the latest {takes.items.length} of {takes.total}.
              </p>
            )}
          </>
        )}
      </section>

      <ConfirmDialog
        open={deleting !== null}
        title="Delete this take?"
        description="Its measurements, its coaching, your feedback on it and, if it was kept, its recording are deleted from this device. This cannot be undone."
        confirmLabel="Delete take"
        onConfirm={() => {
          if (deleting) store.deleteAnalysis(deleting);
          setDeleting(null);
        }}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
